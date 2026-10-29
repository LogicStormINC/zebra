"""SQLite Task segment index queries; no event/body hydration."""

import sqlite3
from uuid import UUID

from agent_core.domain.agent_tasks import ExecutionSegment, RolloverReason, SegmentVisibility
from agent_core.domain.identifiers import SessionId, TaskId

from agent_storage.database import SQLiteDatabase


def read_segment_page(
    database: SQLiteDatabase, task_id: TaskId, *, after_index: int = -1, limit: int = 50
) -> tuple[ExecutionSegment, ...]:
    if (
        type(after_index) is not int
        or after_index < -1
        or type(limit) is not int
        or not 1 <= limit <= 101
    ):
        raise ValueError("invalid segment page bounds")
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM execution_segments WHERE task_id = ? AND segment_index > ? "
            "ORDER BY segment_index LIMIT ?",
            (str(task_id), after_index, limit),
        ).fetchall()
    return tuple(segment_from_row(row) for row in rows)


def segment_from_row(row: sqlite3.Row) -> ExecutionSegment:
    return ExecutionSegment(
        session_id=SessionId(UUID(row["session_id"])),
        task_id=TaskId(UUID(row["task_id"])),
        predecessor_id=(SessionId(UUID(row["predecessor_id"])) if row["predecessor_id"] else None),
        segment_index=row["segment_index"],
        visibility=SegmentVisibility(row["visibility"]),
        rollover_reason=(
            RolloverReason(row["rollover_reason"]) if row["rollover_reason"] else None
        ),
    )
