"""Fold an admitted canonical Run page into bounded execution progress."""

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

from agent_core.contracts.public_output import PublicOutputPayload
from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointConflict
from agent_core.ports.worker_progress import (
    MAX_PROGRESS_KEY_BYTES,
    WorkerProgressHead,
    WorkerProgressState,
    validate_progress_keys,
)

from .commentary_progress import accept_commentary, reserve_commentary
from .public_output import PublicOutputPolicy


@dataclass(frozen=True, slots=True)
class ProgressPageFold:
    head: WorkerProgressHead
    outputs: tuple[tuple[str, int], ...]
    receipts: tuple[tuple[str, int], ...]


def validate_progress_attempt(kind: EventType, payload: Mapping[str, object], current: int) -> None:
    """Reject stale callbacks before persistence as well as during recovery."""
    number = payload.get("attempt_number")
    if kind is EventType.HARNESS_ATTEMPT_STARTED:
        if type(number) is not int or number < current:
            raise CheckpointConflict("Worker progress Attempt moved backwards")
    elif number is not None and (type(number) is not int or number != current):
        raise CheckpointConflict("Worker progress event Attempt disagrees with execution")


def fold_progress_page(
    head: WorkerProgressHead,
    page: TaskEventPage,
    *,
    output_published: Callable[[str], bool],
) -> ProgressPageFold:
    if page.after_sequence != head.through_sequence or not page.events:
        raise CheckpointConflict("Worker progress page does not extend its frontier")
    if any(entry.task_id != head.scope.task_id for entry in page.events):
        raise CheckpointConflict("Worker progress page belongs to another Task")
    values = head.state.model_dump()
    outputs: dict[str, int] = {}
    receipts: dict[str, int] = {}
    for entry in page.events:
        kind, payload = entry.event.event_type, entry.event.payload
        validate_progress_attempt(kind, payload, values["attempt_number"])
        frozen = payload.get("public_output_policy")
        if isinstance(frozen, Mapping):
            policy = PublicOutputPolicy(**dict(frozen))
            encoded = json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"))
            if values["policy_json"] not in (None, encoded):
                raise CheckpointConflict("Worker progress policy changed within its Run")
            values["policy_json"] = encoded
        if kind is EventType.USER_MESSAGE_RECEIVED and values["chinese"] is None:
            content = payload.get("content")
            if isinstance(content, str):
                values["chinese"] = any("\u4e00" <= char <= "\u9fff" for char in content)
        elif kind is EventType.HARNESS_ATTEMPT_STARTED:
            number = payload.get("attempt_number")
            values["attempt_number"], values["attempt_started"] = number, True
        elif kind is EventType.MODEL_REQUEST_STARTED and (
            payload.get("purpose") == "public_expression"
        ):
            values["expression_calls_used"] += 1
        elif kind is EventType.MODEL_RESPONSE_DELTA:
            delta = payload.get("content_delta")
            values["model_spoke"] |= isinstance(delta, str) and bool(delta.strip())
        elif kind is EventType.MODEL_RESPONSE_RECEIVED and (
            payload.get("response_stage") != "public_expression"
        ):
            text = payload.get("assistant_message")
            values["model_spoke"] |= (
                isinstance(text, str) and bool(text.strip()) and (text != "Tool calls proposed.")
            )
            reserve_commentary(payload, entry.task_sequence, values)
        elif kind is EventType.PUBLIC_OUTPUT:
            output = PublicOutputPayload.model_validate(payload)
            if output.output_id in outputs or output_published(output.output_id):
                continue
            if values["terminal"]:
                raise CheckpointConflict("public output follows a terminal Run")
            outputs[output.output_id] = entry.task_sequence
            if output.phase == "model_commentary":
                accept_commentary(output, values)
            else:
                values["published_count"] += 1
            values["started"] |= output.phase == "started"
            values["meaningful"] |= output.meaningful
            values["evidence_published"] |= (
                output.phase == "evidence" and output.evidence_basis is not None
            )
            values["result_published"] |= output.evidence_basis == "verified_result"
            if output.phase == "evidence":
                for reference in output.evidence_refs:
                    validate_progress_keys((reference,))
                    receipts.setdefault(reference, entry.task_sequence)
        elif kind in {
            EventType.ANSWER_COMMITTED,
            EventType.SESSION_CANCELLED,
            EventType.SESSION_FAILED,
        }:
            values["terminal"] = True
    key_bytes = sum(len(key.encode("utf-8")) + 128 for key in (*outputs, *receipts))
    if key_bytes > MAX_PROGRESS_KEY_BYTES:
        # ponytail: retry maintenance with a smaller canonical page, never drop
        # references or load all membership rows. A single public event is bounded.
        raise ValueError("Worker progress transition exceeds key byte bound")
    state = WorkerProgressState.model_validate(values)
    latest = page.events[-1]
    return ProgressPageFold(
        WorkerProgressHead(head.scope, page.next_sequence, latest.event.event_id, state),
        tuple(outputs.items()),
        tuple(receipts.items()),
    )
