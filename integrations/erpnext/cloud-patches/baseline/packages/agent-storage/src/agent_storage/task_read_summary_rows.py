"""Bounded canonical derivation and codec shared by the two native adapters."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agent_core.application.session_attachments import attachment_refs_from_event
from agent_core.application.task_model_usage import advance_model_usage, public_model_usage
from agent_core.application.task_turn_fields import SegmentTurnReadState, advance_segment_turns
from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.agent_tasks import TaskEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_read_summaries import TaskAttachmentEntry, TaskReadSummary


def encoded(value: object, maximum: int = 65_536) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > maximum:
        raise CheckpointConflict("Task summary metadata exceeds its byte budget")
    return text


def usage_state(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > 65_536:
        raise CheckpointConflict("Task usage state exceeds its byte budget")
    try:
        state = json.loads(text)
    except ValueError as exc:
        raise CheckpointConflict("invalid persisted Task usage state") from exc
    if state == {}:
        return {}
    keys = {"model_call_count", "cache_hit_tokens", "cache_miss_tokens", "latest"}
    if (
        not isinstance(state, dict)
        or not keys <= set(state) <= keys | {"turn_state"}
        or not isinstance(state["latest"], dict)
    ):
        raise CheckpointConflict("invalid persisted Task usage state")
    if any(type(state[key]) is not int or state[key] < 0 for key in keys - {"latest"}):
        raise CheckpointConflict("invalid persisted Task usage counters")
    return state


def turn_state(state: dict[str, Any], through: int) -> dict[str, Any]:
    empty = {"version": 3, "through_sequence": -1, "segments": {}}
    value = state.get("turn_state", empty)
    if (
        not isinstance(value, dict)
        or set(value)
        not in ({"through_sequence", "segments"}, {"version", "through_sequence", "segments"})
        or type(value["through_sequence"]) is not int
        or not -1 <= value["through_sequence"] <= through
        or not isinstance(value["segments"], dict)
    ):
        raise CheckpointConflict("invalid persisted Turn summary coverage")
    if "version" not in value or value["version"] == 2:
        # Old derived state omitted the canonical lookup alias. Rebuild only in
        # the existing bounded writer; GET observes pending without any repair.
        return empty
    if type(value["version"]) is not int or value["version"] != 3:
        raise CheckpointConflict("unsupported persisted Turn summary version")
    if any(
        not isinstance(segment, dict) or "human_turn_count" not in segment
        for segment in value["segments"].values()
    ):
        raise CheckpointConflict("Turn summary lacks exact cumulative human count")
    return value


def advance_turn_page(state: dict[str, Any], page: TaskEventPage) -> str:
    value = turn_state(state, page.highwater)
    if value["through_sequence"] != page.after_sequence:
        raise CheckpointConflict("Turn summary page conflicts with its persisted prefix")
    segments = dict(value["segments"])
    try:
        for item in page.events:
            advance_segment_turns(segments, item.event)
    except ValueError as exc:
        raise CheckpointConflict("invalid persisted Turn projection state") from exc
    updated = (
        state
        if "model_call_count" in state
        else {
            "model_call_count": 0,
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
            "latest": {},
            **state,
        }
    )
    updated["turn_state"] = {
        "version": 3,
        "through_sequence": page.next_sequence,
        "segments": segments,
    }
    return encoded(updated)


def summary_from_row(
    task_id: TaskId, highwater: int, row: Any, active_segment_id: SessionId
) -> TaskReadSummary:
    try:
        state = usage_state(row["usage_state_json"]) if row else {}
        through = row["through_sequence"] if row else -1
        turns = turn_state(state, through)
        segment = turns["segments"].get(str(active_segment_id))
        fields = (
            SegmentTurnReadState.model_validate(segment).public_fields()
            if segment is not None and turns["through_sequence"] == through
            else None
        )
        return TaskReadSummary(
            task_id,
            through,
            highwater,
            public_model_usage(state),
            row["attachment_count"] if row else 0,
            row["attachment_bytes"] if row else 0,
            SessionId(UUID(str(active_segment_id))),
            fields,
        )
    except ValueError as exc:
        raise CheckpointConflict("invalid persisted Task summary frontier") from exc


def validate_attachment_sources(rows: list[Any], task_id: TaskId, through: int) -> None:
    for row in rows:
        if (
            str(row["source_task"]) != str(task_id)
            or str(row["member_task"]) != str(task_id)
            or row["source_position"] != row["task_sequence"]
            or row["task_sequence"] > through
            or str(row["session_id"]) != str(row["segment_id"])
            or row["source_sequence"] != row["segment_sequence"]
            or row["event_type"] != EventType.USER_MESSAGE_RECEIVED.value
        ):
            raise CheckpointConflict("attachment frontier conflicts with canonical source")
        if not row["event_position_source_ready"]:
            raise CheckpointNotReady("Task attachment Segment requires explicit repair")
        if row["source_sequence"] > row["event_position_source_cursor"]:
            raise CheckpointConflict("attachment frontier exceeds canonical Segment coverage")


def attachment_from_row(row: Any) -> TaskAttachmentEntry:
    text = row["ref_json"]
    if len(text.encode("utf-8")) != row["ref_bytes"]:
        raise CheckpointConflict("indexed attachment byte bound conflicts with reference")
    try:
        ref = SessionAttachmentRef.model_validate_json(text)
    except ValueError as exc:
        raise CheckpointConflict("invalid persisted attachment reference") from exc
    if str(ref.message_event_id) != str(row["event_id"]):
        raise CheckpointConflict("attachment reference conflicts with canonical user Event")
    return TaskAttachmentEntry(row["ordinal"], row["task_sequence"], ref)


def admit_attachment_rows(
    rows: list[Any],
    after: int,
    count: int,
    max_bytes: int,
    *,
    limit: int,
) -> tuple[int, int]:
    if len(rows) != min(limit, count - after - 1):
        raise CheckpointConflict("indexed attachment page has missing coverage")
    size = 0
    admitted = 0
    for ordinal, row in enumerate(rows, after + 1):
        if row["ordinal"] != ordinal or ordinal >= count:
            raise CheckpointConflict("indexed attachment page has missing coverage")
        bound = row["ref_bytes"]
        if type(bound) is not int or bound <= 0:
            raise CheckpointConflict("invalid indexed attachment byte bound")
        if size + bound > max_bytes:
            if not admitted:
                raise CheckpointConflict("one attachment reference exceeds the page budget")
            break
        size += bound
        admitted += 1
    if not admitted and after < count - 1:
        raise CheckpointConflict("indexed attachment page omits captured coverage")
    return admitted, size


def page_request(after: int, limit: int, max_bytes: int, through: int | None) -> None:
    if type(after) is not int or not -1 <= after <= 2**63 - 1:
        raise ValueError("invalid attachment cursor")
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("attachment page limit must be between 1 and 256")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1_048_576:
        raise ValueError("attachment page bytes must be between 1 and 1048576")
    if through is not None and (type(through) is not int or not -1 <= through <= 2**63 - 1):
        raise ValueError("invalid attachment source window")


@dataclass(frozen=True)
class SummaryDerivation:
    usage_json: str
    frontiers: tuple[tuple[object, ...], ...]
    attachments: tuple[tuple[object, ...], ...]
    count: int
    size: int


def derive_page(page: TaskEventPage, head: Any) -> SummaryDerivation:
    state = usage_state(head["usage_state_json"])
    turns = turn_state(state, head["through_sequence"])
    count, size = head["attachment_count"], head["attachment_bytes"]
    frontiers: list[tuple[object, ...]] = []
    attachments: list[tuple[object, ...]] = []
    for item in page.events:
        if item.event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
            state = advance_model_usage(state, item.event.payload)
        for index, ref in enumerate(attachment_refs_from_event(item.event)):
            text = encoded(ref.to_mapping(), 1_048_576)
            attachments.append((count, item.task_sequence, index, text, len(text.encode("utf-8"))))
            count += 1
            size += ref.size_bytes
        frontiers.append(
            (
                item.task_sequence,
                str(item.event.event_id),
                str(item.segment_id),
                item.segment_sequence,
                count,
                size,
            )
        )
    state["turn_state"] = turns
    return SummaryDerivation(
        advance_turn_page(state, page), tuple(frontiers), tuple(attachments), count, size
    )
