"""SQLite Task seek pages: bounded metadata first, budgeted bodies second."""

import sqlite3
from uuid import UUID

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage

from agent_storage.event_rows import deserialize_event_row
from agent_storage.task_event_page_limits import (
    admitted_page_positions,
    build_event_page,
    page_highwater,
    validate_page_request,
)


def read_task_event_page(
    connection: sqlite3.Connection,
    task_id: TaskId,
    after: int,
    *,
    limit: int,
    max_bytes: int,
    through: int | None,
) -> TaskEventPage:
    validate_page_request(after, limit, max_bytes, through)
    key = str(task_id)
    header = connection.execute(
        "SELECT next_event_sequence,event_position_state FROM agent_tasks WHERE task_id=?",
        (key,),
    ).fetchone()
    if header is None:
        raise ValueError("Task page target was not found")
    if header["event_position_state"] != "ready":
        raise ValueError("Task Event positions require explicit backfill")
    highwater = page_highwater(after, header["next_event_sequence"], through)
    metadata = connection.execute(
        """SELECT event.task_sequence,member.task_id AS member_task,
                  event.event_bytes_bound AS source_bytes
           FROM session_events event LEFT JOIN execution_segments member
             ON member.session_id=event.session_id
           WHERE event.task_id=? AND event.task_sequence>? AND event.task_sequence<=?
           ORDER BY event.task_sequence LIMIT ?""",
        (key, after, highwater, limit),
    ).fetchall()
    if any(row["member_task"] != key for row in metadata):
        raise ValueError("canonical Task page conflicts with membership")
    if any(row["source_bytes"] is None for row in metadata):
        raise ValueError("Event byte bounds require explicit backfill")
    positions = admitted_page_positions(
        [(row["task_sequence"], row["source_bytes"]) for row in metadata],
        after=after,
        highwater=highwater,
        max_bytes=max_bytes,
    )
    if not positions:
        return build_event_page((), after=after, highwater=highwater, max_bytes=max_bytes)
    rows = connection.execute(
        """SELECT * FROM session_events WHERE task_id=? AND task_sequence>?
           AND task_sequence<=? ORDER BY task_sequence LIMIT ?""",
        (key, after, positions[-1], len(positions)),
    ).fetchall()
    events = tuple(
        TaskEvent(
            task_id=task_id,
            task_sequence=row["task_sequence"],
            segment_id=SessionId(UUID(row["session_id"])),
            segment_sequence=row["sequence"],
            event=deserialize_event_row(row),
        )
        for row in rows
    )
    if len(events) != len(positions):
        raise ValueError("canonical Task page changed during its bounded read")
    return build_event_page(events, after=after, highwater=highwater, max_bytes=max_bytes)
