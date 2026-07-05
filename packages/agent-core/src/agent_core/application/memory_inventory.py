from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from shlex import join as shell_join
from typing import Any

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.memories import MemoryRecord


def serialize_memory_inventory(
    records: Sequence[MemoryRecord],
    events: Iterable[SessionEvent],
) -> list[dict[str, Any]]:
    event_index = {event.sequence: event for event in events}
    latest_reviews = _latest_review_payloads(events)
    return [
        _serialize_inventory_row(record, event_index, latest_reviews)
        for record in records
    ]


def serialize_scoped_memory_inventory(
    records: Sequence[MemoryRecord],
    load_events: Callable[[SessionId], Iterable[SessionEvent]],
) -> list[dict[str, Any]]:
    cache: dict[SessionId, tuple[dict[int, SessionEvent], dict[str, dict[str, Any]]]] = {}
    rows: list[dict[str, Any]] = []
    for record in records:
        event_index: dict[int, SessionEvent] = {}
        latest_reviews: dict[str, dict[str, Any]] = {}
        if record.source_session_id is not None:
            cached = cache.get(record.source_session_id)
            if cached is None:
                events = tuple(load_events(record.source_session_id))
                cached = (
                    {event.sequence: event for event in events},
                    _latest_review_payloads(events),
                )
                cache[record.source_session_id] = cached
            event_index, latest_reviews = cached
        rows.append(_serialize_inventory_row(record, event_index, latest_reviews))
    return rows


def _latest_review_payloads(events: Iterable[SessionEvent]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type is not EventType.MEMORY_REVIEW_RECORDED:
            continue
        memory_id = event.payload.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id.strip():
            continue
        latest[memory_id] = {
            "recorded_at": event.created_at.isoformat(),
            "previous_status": event.payload["previous_status"],
            "status": event.payload["status"],
            "operator": event.payload["operator"],
            "reason": event.payload["reason"],
            "superseded_memory_ids": list(event.payload["superseded_memory_ids"]),
            "duplicate_of_memory_id": event.payload["duplicate_of_memory_id"],
        }
    return latest


def _serialize_inventory_row(
    record: MemoryRecord,
    event_index: dict[int, SessionEvent],
    latest_reviews: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        **record.model_dump(mode="json"),
        "source": _serialize_memory_source(record, event_index),
        "last_review": latest_reviews.get(str(record.memory_id)),
    }


def _serialize_memory_source(
    record: MemoryRecord,
    event_index: dict[int, SessionEvent],
) -> dict[str, Any] | None:
    if record.source_event_start is None:
        return None
    event = event_index.get(record.source_event_start)
    if event is None:
        return {
            "kind": "event_range",
            "event_type": None,
            "source_event_start": record.source_event_start,
            "source_event_end": record.source_event_end,
            "captured_at": record.created_at.isoformat(),
        }
    if event.event_type is EventType.TOOL_EXECUTION_COMPLETED:
        return _tool_source(record, event)
    if event.event_type is EventType.USER_MESSAGE_RECEIVED:
        return {
            "kind": "user_message",
            "event_type": event.event_type.value,
            "source_event_start": record.source_event_start,
            "source_event_end": record.source_event_end,
            "captured_at": event.created_at.isoformat(),
        }
    return {
        "kind": "session_event",
        "event_type": event.event_type.value,
        "source_event_start": record.source_event_start,
        "source_event_end": record.source_event_end,
        "captured_at": event.created_at.isoformat(),
    }


def _tool_source(record: MemoryRecord, event: SessionEvent) -> dict[str, Any]:
    metadata = event.payload.get("metadata")
    tool_name = event.payload.get("tool_name")
    if not isinstance(metadata, dict) or not isinstance(tool_name, str):
        return {
            "kind": "tool",
            "event_type": event.event_type.value,
            "tool_name": tool_name,
            "source_event_start": record.source_event_start,
            "source_event_end": record.source_event_end,
            "captured_at": event.created_at.isoformat(),
        }
    source: dict[str, Any] = {
        "kind": "tool",
        "event_type": event.event_type.value,
        "tool_name": tool_name,
        "source_event_start": record.source_event_start,
        "source_event_end": record.source_event_end,
        "captured_at": event.created_at.isoformat(),
    }
    path = _optional_text(metadata.get("path"))
    if path is not None:
        source["locator"] = path
        return source
    command = _command_parts(metadata.get("command"))
    cwd = _optional_text(metadata.get("cwd"))
    preset = _optional_text(metadata.get("preset"))
    if command is not None:
        source["locator"] = shell_join(command)
    if cwd is not None:
        source["cwd"] = cwd
    if preset is not None:
        source["preset"] = preset
    return source


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _command_parts(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    parts: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        stripped = item.strip()
        if not stripped:
            return None
        parts.append(stripped)
    return tuple(parts) if parts else None
