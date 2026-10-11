"""Shared byte admission for indexed Task metadata before body hydration."""

import json
from collections.abc import Sequence

from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage


def validate_page_request(after: int, limit: int, max_bytes: int, through: int | None) -> None:
    if type(after) is not int or after < -1:
        raise ValueError("Task page cursor must be an integer greater than or equal to -1")
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("Task page limit must be between 1 and 256")
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 1_048_576:
        raise ValueError("Task page byte budget must be between 1024 and 1048576")
    if through is not None and (type(through) is not int or through < after):
        raise ValueError("invalid Task page highwater")


def page_highwater(after: int, next_sequence: int, through: int | None) -> int:
    highwater = next_sequence - 1 if through is None else through
    if not after <= highwater <= next_sequence - 1:
        raise ValueError("Task page cursor or highwater is outside canonical source")
    return highwater


def admitted_page_positions(
    metadata: Sequence[tuple[int, int]],
    *,
    after: int,
    highwater: int,
    max_bytes: int,
) -> tuple[int, ...]:
    positions: list[int] = []
    size = 0
    for position, source_bytes in metadata:
        if position != after + len(positions) + 1 or position > highwater:
            raise ValueError("canonical Task page has a position gap")
        if source_bytes <= 0:
            raise ValueError("canonical Task page has invalid byte metadata")
        if size + source_bytes > max_bytes:
            if not positions:
                raise ValueError(f"Task Event {position} exceeds the page byte budget")
            break
        positions.append(position)
        size += source_bytes
    if not positions and after != highwater:
        raise ValueError("canonical Task page omits source coverage")
    return tuple(positions)


def build_event_page(
    events: tuple[TaskEvent, ...],
    *,
    after: int,
    highwater: int,
    max_bytes: int,
) -> TaskEventPage:
    byte_count = sum(
        len(
            json.dumps(
                {
                    "task_id": str(entry.task_id),
                    "task_sequence": entry.task_sequence,
                    "segment_id": str(entry.segment_id),
                    "segment_sequence": entry.segment_sequence,
                    "event": entry.event.model_dump(mode="json"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        for entry in events
    )
    if byte_count > max_bytes:
        raise ValueError("Task page serialization exceeds its admitted byte budget")
    return TaskEventPage(events, after, highwater, byte_count)
