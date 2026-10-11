"""Exact point-state dependencies of the unchanged AG-UI projector."""

import json
from collections.abc import Iterator

from ag_ui.core import CustomEvent, Event, RunStartedEvent
from agent_core.domain.events import EventType, SessionEvent
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_BYTES,
    MAX_EVENT_FRAMES,
    CellKind,
    ProjectionCellKey,
)

from agent_integrations.ag_ui.client_state_projection import project_client_state
from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.payload_validation import optional_payload_text, required_payload_text
from agent_integrations.ag_ui.projection_state import ProjectionState


def projection_keys(
    event: SessionEvent, *, message_id: str | None = None
) -> tuple[ProjectionCellKey, ...]:
    keys: list[ProjectionCellKey] = []
    payload = event.payload
    kind = event.event_type

    def add(cell_kind: CellKind, key: str) -> None:
        keys.append(ProjectionCellKey(event.session_id, cell_kind, key))

    if kind in {EventType.MODEL_RESPONSE_DELTA, EventType.MODEL_RESPONSE_RECEIVED}:
        call = (
            required_payload_text(payload, "model_call_id")
            if kind is EventType.MODEL_RESPONSE_DELTA
            else optional_payload_text(payload, "model_call_id") or str(event.event_id)
        )
        add("text_message", call)
        # Preserve both existing key conventions; do not change projector semantics.
        add("text_ended", call)
        add("text_ended", message_id or f"message:{call}")
    elif kind in {
        EventType.TOOL_CALL_PROPOSED,
        EventType.TOOL_EXECUTION_COMPLETED,
        EventType.TOOL_EXECUTION_FAILED,
    }:
        add("tool_call", required_payload_text(payload, "tool_call_id"))
    elif kind in {
        EventType.APPROVAL_REQUESTED,
        EventType.APPROVAL_GRANTED,
        EventType.APPROVAL_REJECTED,
    }:
        add(
            "interrupt",
            f"approval:{optional_payload_text(payload, 'tool_call_id') or event.event_id}",
        )
    elif kind in {EventType.CLARIFICATION_REQUESTED, EventType.CLARIFICATION_RESPONDED}:
        add(
            "interrupt",
            f"clarification:{optional_payload_text(payload, 'clarification_id') or event.event_id}",
        )
    return tuple(dict.fromkeys(keys))


def settle_interrupt_membership(event: SessionEvent, state: ProjectionState) -> None:
    if event.event_type not in {
        EventType.APPROVAL_GRANTED,
        EventType.APPROVAL_REJECTED,
        EventType.CLARIFICATION_RESPONDED,
    }:
        return
    for key in projection_keys(event):
        state.checkpoint_interrupt_ids.discard(key.key)
        state.open_interrupts.pop(key.key, None)


def admit_projection(event: SessionEvent, identity: AgUiRunIdentity, *, started: bool) -> None:
    """Bound source size/depth/work and variable fanout before invoking projector.

    Fixed-fanout branches produce at most 13 frames from this bounded source.
    The command's unbounded child-results branch gets an exact count and byte
    preflight, allocating only one candidate frame at a time.
    """
    stack: list[Iterator[object]] = [iter((event.payload,))]
    nodes = 0
    while stack:
        try:
            value = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        nodes += 1
        if nodes > 65_536 or len(stack) > 64:
            raise AgUiProjectionError("durable Event exceeds JSON work/depth bound")
        if isinstance(value, dict):
            if len(value) > 65_536 or any(
                not isinstance(key, str) or len(key) > MAX_CHECKPOINT_BYTES for key in value
            ):
                raise AgUiProjectionError("durable Event has invalid JSON keys")
            stack.append(iter(value.values()))
        elif isinstance(value, list):
            stack.append(iter(value))
        elif isinstance(value, str):
            if len(value) > MAX_CHECKPOINT_BYTES:
                raise AgUiProjectionError("durable Event exceeds source byte bound")
        elif value is not None and not isinstance(value, int | float | bool):
            raise AgUiProjectionError("durable Event is not JSON data")
    try:
        size = 0
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(
            event.payload
        ):
            size += len(chunk.encode())
            if size > MAX_CHECKPOINT_BYTES:
                raise AgUiProjectionError("durable Event exceeds source byte bound")
    except (TypeError, ValueError, RecursionError) as exc:
        raise AgUiProjectionError("durable Event failed bounded JSON admission") from exc
    if event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
        return
    command = event.payload.get("payload")
    children = command.get("child_results") if isinstance(command, dict) else None
    if not isinstance(children, list):
        return
    client_frames = project_client_state(event, timestamp=int(event.created_at.timestamp() * 1000))
    candidates: list[Event] = list(client_frames or ())
    if not started:
        candidates.append(RunStartedEvent(thread_id=identity.thread_id, run_id=identity.run_id))
    count = len(candidates)
    size = sum(
        len(frame.model_dump_json(by_alias=True, exclude_none=True).encode())
        for frame in candidates
    )
    if size > MAX_CHECKPOINT_BYTES:
        raise AgUiProjectionError("durable Event exceeds frame byte bound before projection")
    for child in children:
        if not isinstance(child, dict):
            continue
        task = optional_payload_text(child, "child_task_id")
        status = optional_payload_text(child, "status")
        if task is None or status is None:
            continue
        count += 1
        if count > MAX_EVENT_FRAMES:
            raise AgUiProjectionError("durable Event exceeds frame-count bound before projection")
        frame = CustomEvent(
            timestamp=int(event.created_at.timestamp() * 1000),
            name="zebra.subagent",
            value={"child_task_id": task, "status": status},
        )
        size += len(frame.model_dump_json(by_alias=True, exclude_none=True).encode())
        if size > MAX_CHECKPOINT_BYTES:
            raise AgUiProjectionError("durable Event exceeds frame byte bound before projection")
