from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from agent_core.domain.agent_tasks import (
    AgentTask,
    ExecutionSegment,
    RolloverReason,
    SegmentVisibility,
)
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.plans import SessionPlan
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEvent

from agent_storage.database import SQLiteDatabase
from agent_storage.event_rows import deserialize_event_row
from agent_storage.projections import SQLiteProjectionStore
from agent_storage.session_handoff_rows import SCHEMA as HANDOFF_SCHEMA
from agent_storage.sqlite import SQLiteEventStore

TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id TEXT PRIMARY KEY,
    root_session_id TEXT NOT NULL UNIQUE,
    active_segment_id TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'local',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_segments (
    session_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    predecessor_id TEXT,
    segment_index INTEGER NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'internal',
    rollover_reason TEXT,
    UNIQUE(task_id, segment_index)
);
CREATE INDEX IF NOT EXISTS idx_execution_segments_task
ON execution_segments(task_id, segment_index);
CREATE TABLE IF NOT EXISTS task_event_index (
    task_id TEXT NOT NULL,
    task_sequence INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    segment_id TEXT NOT NULL,
    segment_sequence INTEGER NOT NULL,
    PRIMARY KEY(task_id, task_sequence)
);
"""


class SQLiteAgentTaskStore(AgentTaskPort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        SQLiteEventStore(database_path)
        SQLiteProjectionStore(database_path)
        with self._database.connect() as connection:
            connection.executescript(HANDOFF_SCHEMA)
            connection.executescript(TASK_SCHEMA)

    def ensure_for_session(self, session_id: SessionId) -> AgentTask:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task_id = _ensure_task_locked(connection, session_id)
            _sync_events_locked(connection, task_id)
            return _task_from_connection(connection, task_id)

    def rebuild_all(self) -> int:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sessions = connection.execute(
                "SELECT session_id FROM session_projections ORDER BY created_at, session_id"
            ).fetchall()
            task_ids = {
                _ensure_task_locked(connection, SessionId(UUID(row[0]))) for row in sessions
            }
            for task_id in task_ids:
                _sync_events_locked(connection, task_id)
            return len(task_ids)

    def get_task(self, task_id: TaskId) -> AgentTask | None:
        with self._database.connect() as connection:
            if not _task_exists(connection, task_id):
                root = SessionId(UUID(str(task_id)))
                if not _session_exists(connection, root):
                    return None
                connection.execute("BEGIN IMMEDIATE")
                _ensure_task_locked(connection, root)
            else:
                connection.execute("BEGIN IMMEDIATE")
            _sync_events_locked(connection, task_id)
            return _task_from_connection(connection, task_id)

    def list_tasks(self, *, limit: int) -> tuple[AgentTask, ...]:
        if limit <= 0:
            return ()
        self.rebuild_all()
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT task_id FROM agent_tasks ORDER BY updated_at DESC, task_id LIMIT ?",
                (limit,),
            ).fetchall()
            return tuple(_task_from_connection(connection, TaskId(UUID(row[0]))) for row in rows)

    def segments(self, task_id: TaskId) -> tuple[ExecutionSegment, ...]:
        if self.get_task(task_id) is None:
            return ()
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM execution_segments WHERE task_id = ? ORDER BY segment_index",
                (str(task_id),),
            ).fetchall()
        return tuple(_segment_from_row(row) for row in rows)

    def active_segment(self, task_id: TaskId) -> SessionId | None:
        task = self.get_task(task_id)
        return None if task is None else task.active_segment_id

    def is_internal_segment(self, session_id: SessionId) -> bool:
        try:
            task = self.ensure_for_session(session_id)
        except ValueError:
            return False
        return str(task.task_id) != str(session_id)

    def attach_segment(
        self,
        task_id: TaskId,
        segment_id: SessionId,
        *,
        predecessor_id: SessionId,
        reason: RolloverReason,
    ) -> AgentTask:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attach_segment_locked(
                connection,
                task_id=task_id,
                segment_id=segment_id,
                predecessor_id=predecessor_id,
                reason=reason,
            )
            _sync_events_locked(connection, task_id)
            return _task_from_connection(connection, task_id)

    def read_events(self, task_id: TaskId, after_sequence: int) -> tuple[TaskEvent, ...]:
        if after_sequence < -1:
            raise ValueError("task event cursor must be greater than or equal to -1")
        if self.get_task(task_id) is None:
            return ()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT i.task_sequence, i.segment_id, i.segment_sequence, e.*
                FROM task_event_index i
                JOIN session_events e ON e.event_id = i.event_id
                WHERE i.task_id = ? AND i.task_sequence > ?
                ORDER BY i.task_sequence
                """,
                (str(task_id), after_sequence),
            ).fetchall()
        return tuple(
            TaskEvent(
                task_id=task_id,
                task_sequence=row["task_sequence"],
                segment_id=SessionId(UUID(row["segment_id"])),
                segment_sequence=row["segment_sequence"],
                event=deserialize_event_row(row),
            )
            for row in rows
        )


def attach_segment_locked(
    connection: sqlite3.Connection,
    *,
    task_id: TaskId,
    segment_id: SessionId,
    predecessor_id: SessionId,
    reason: RolloverReason,
) -> None:
    _ensure_task_locked(connection, predecessor_id)
    active = connection.execute(
        "SELECT active_segment_id FROM agent_tasks WHERE task_id = ?", (str(task_id),)
    ).fetchone()
    if active is None or active[0] != str(predecessor_id):
        raise ValueError("task active Segment changed during rollover")
    predecessor = connection.execute(
        "SELECT segment_index FROM execution_segments WHERE session_id = ?",
        (str(predecessor_id),),
    ).fetchone()
    if predecessor is None:
        raise ValueError("rollover predecessor is not indexed")
    connection.execute(
        """
        INSERT OR IGNORE INTO execution_segments
        VALUES (?, ?, ?, ?, 'internal', ?)
        """,
        (
            str(segment_id),
            str(task_id),
            str(predecessor_id),
            predecessor[0] + 1,
            reason.value,
        ),
    )
    updated = connection.execute(
        """
        UPDATE agent_tasks SET active_segment_id = ?, updated_at =
            (SELECT updated_at FROM session_projections WHERE session_id = ?)
        WHERE task_id = ? AND active_segment_id = ?
        """,
        (str(segment_id), str(segment_id), str(task_id), str(predecessor_id)),
    )
    if updated.rowcount != 1:
        raise ValueError("task active Segment CAS failed")


def attach_handoff_segment_locked(
    connection: sqlite3.Connection,
    *,
    root_session_id: SessionId,
    segment_id: SessionId,
    predecessor_id: SessionId,
    handoff_reason: str,
) -> bool:
    reason = {
        "internal_recovery": RolloverReason.RECOVERY,
        "internal_terminal_follow_up": RolloverReason.TERMINAL_FOLLOW_UP,
        "internal_agent_hint": RolloverReason.AGENT_HINT,
    }.get(handoff_reason, RolloverReason.CONTEXT_PRESSURE)
    try:
        attach_segment_locked(
            connection,
            task_id=TaskId(UUID(str(root_session_id))),
            segment_id=segment_id,
            predecessor_id=predecessor_id,
            reason=reason,
        )
    except ValueError:
        return False
    return True


def _ensure_task_locked(connection: sqlite3.Connection, session_id: SessionId) -> TaskId:
    lineage = connection.execute(
        "SELECT root_session_id FROM session_lineage WHERE session_id = ?", (str(session_id),)
    ).fetchone()
    root_id = SessionId(UUID(lineage[0])) if lineage is not None else session_id
    root = connection.execute(
        "SELECT created_at, updated_at FROM session_projections WHERE session_id = ?",
        (str(root_id),),
    ).fetchone()
    if root is None:
        raise ValueError("task root Session was not found")
    task_id = TaskId(UUID(str(root_id)))
    lineage_rows = connection.execute(
        "SELECT * FROM session_lineage WHERE root_session_id = ? ORDER BY stage_index",
        (str(root_id),),
    ).fetchall()
    lineage_values: list[dict[str, object]] = [dict(row) for row in lineage_rows] or [
        {
            "session_id": str(root_id),
            "parent_session_id": None,
            "stage_index": 0,
            "inbound_handoff_id": None,
        }
    ]
    active_id = str(lineage_values[-1]["session_id"])
    active = connection.execute(
        "SELECT updated_at FROM session_projections WHERE session_id = ?", (active_id,)
    ).fetchone()
    connection.execute(
        """
        INSERT INTO agent_tasks VALUES (?, ?, ?, 'local', ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            active_segment_id = excluded.active_segment_id,
            updated_at = excluded.updated_at
        """,
        (str(task_id), str(root_id), active_id, root["created_at"], active[0]),
    )
    for row in lineage_values:
        reason = None if row["stage_index"] == 0 else RolloverReason.TERMINAL_FOLLOW_UP.value
        connection.execute(
            "INSERT OR IGNORE INTO execution_segments VALUES (?, ?, ?, ?, 'internal', ?)",
            (
                row["session_id"],
                str(task_id),
                row["parent_session_id"],
                row["stage_index"],
                reason,
            ),
        )
    return task_id


def _sync_events_locked(connection: sqlite3.Connection, task_id: TaskId) -> None:
    segments = connection.execute(
        "SELECT session_id FROM execution_segments WHERE task_id = ? ORDER BY segment_index",
        (str(task_id),),
    ).fetchall()
    next_sequence = connection.execute(
        "SELECT COALESCE(MAX(task_sequence), -1) + 1 FROM task_event_index WHERE task_id = ?",
        (str(task_id),),
    ).fetchone()[0]
    for segment in segments:
        events = connection.execute(
            """
            SELECT event_id, sequence FROM session_events
            WHERE session_id = ? ORDER BY sequence
            """,
            (segment[0],),
        ).fetchall()
        for event in events:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO task_event_index VALUES (?, ?, ?, ?, ?)
                """,
                (str(task_id), next_sequence, event["event_id"], segment[0], event["sequence"]),
            )
            if cursor.rowcount == 1:
                next_sequence += 1


def _task_from_connection(connection: sqlite3.Connection, task_id: TaskId) -> AgentTask:
    row = connection.execute(
        """
        SELECT t.*, p.title, p.status, p.current_sequence AS segment_sequence
        FROM agent_tasks t
        JOIN session_projections p ON p.session_id = t.active_segment_id
        WHERE t.task_id = ?
        """,
        (str(task_id),),
    ).fetchone()
    if row is None:
        raise ValueError("task projection is incomplete")
    current = connection.execute(
        "SELECT COALESCE(MAX(task_sequence), -1) FROM task_event_index WHERE task_id = ?",
        (str(task_id),),
    ).fetchone()[0]
    return AgentTask(
        task_id=task_id,
        title=row["title"],
        goal=_task_goal(connection, row["root_session_id"]),
        plan_required=_task_plan_required(connection, row["root_session_id"]),
        task_plan=_task_plan(connection, task_id),
        status=SessionStatus(row["status"]),
        active_segment_id=SessionId(UUID(row["active_segment_id"])),
        current_sequence=max(current, row["segment_sequence"]),
        namespace=row["namespace"],
    )


def _task_goal(connection: sqlite3.Connection, root_session_id: str) -> str:
    """Project the canonical task goal.

    W5-P3A: the goal MUST come from the latest explicit Goal event when one
    exists; that goal_text is the only
    source that may be re-injected as a SYSTEM Stable Task Goal by
    ``append_task_state_context``. When no TASK_GOAL_SET has been
    emitted, we fall back to the public_content / content of the first
    USER_MESSAGE_RECEIVED for backward compatibility with pre-P3A
    callers (this projection is informational; it is NOT emitted as
    a SYSTEM block by ``append_task_state_context`` when the goal is
    not explicitly anchored).
    """
    row = connection.execute(
        """
        SELECT e.*
        FROM session_events e
        LEFT JOIN session_lineage l ON l.session_id = e.session_id
        WHERE COALESCE(l.root_session_id, e.session_id) = ?
          AND e.event_type IN (?, ?)
        ORDER BY COALESCE(l.stage_index, 0) DESC, e.sequence DESC
        LIMIT 1
        """,
        (
            root_session_id,
            EventType.TASK_GOAL_SET.value,
            EventType.TASK_GOAL_REVISED.value,
        ),
    ).fetchone()
    if row is not None:
        payload = deserialize_event_row(row).payload
        goal_text = payload.get("goal_text")
        if isinstance(goal_text, str) and goal_text.strip():
            return goal_text.strip()
        # Goal-bound TASK_GOAL_SET without text falls back to the durable
        # session title so the goal projection never silently degrades to
        # the first user message body.
        binding = payload.get("binding")
        if binding == "goal_bound":
            projection = connection.execute(
                "SELECT title FROM session_projections WHERE session_id = ?",
                (root_session_id,),
            ).fetchone()
            if projection is None:
                raise ValueError("task goal projection is incomplete")
            return str(projection["title"]).strip()
    # Legacy path: read the first USER_MESSAGE_RECEIVED body. The
    # resulting string is exposed via task.goal for legacy callers;
    # ``append_task_state_context`` checks whether an explicit
    # TASK_GOAL_SET anchor exists before re-injecting it as SYSTEM.
    legacy = connection.execute(
        """
        SELECT * FROM session_events
        WHERE session_id = ? AND event_type = ?
        ORDER BY sequence LIMIT 1
        """,
        (root_session_id, EventType.USER_MESSAGE_RECEIVED.value),
    ).fetchone()
    if legacy is not None:
        payload = deserialize_event_row(legacy).payload
        goal = payload.get("public_content", payload.get("content"))
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("task goal projection is invalid")
        return goal.strip()
    projection = connection.execute(
        "SELECT title FROM session_projections WHERE session_id = ?",
        (root_session_id,),
    ).fetchone()
    if projection is None:
        raise ValueError("task goal projection is incomplete")
    title = projection["title"]
    if isinstance(title, str) and title.strip():
        return title.strip()
    return ""


def _task_plan_required(connection: sqlite3.Connection, root_session_id: str) -> bool:
    row = connection.execute(
        """
        SELECT * FROM session_events
        WHERE session_id = ? AND event_type = ?
        ORDER BY sequence LIMIT 1
        """,
        (root_session_id, EventType.TASK_PREPARED.value),
    ).fetchone()
    if row is None:
        return False
    value = deserialize_event_row(row).payload.get("plan_required", False)
    if not isinstance(value, bool):
        raise ValueError("task plan_required projection is invalid")
    return value


def _task_plan(connection: sqlite3.Connection, task_id: TaskId) -> SessionPlan:
    row = connection.execute(
        """
        SELECT e.* FROM task_event_index i
        JOIN session_events e ON e.event_id = i.event_id
        WHERE i.task_id = ? AND e.event_type = ?
        ORDER BY i.task_sequence DESC LIMIT 1
        """,
        (str(task_id), EventType.PLAN_UPDATED.value),
    ).fetchone()
    if row is None:
        return SessionPlan()
    event = deserialize_event_row(row)
    return SessionPlan.model_validate(
        {"steps": event.payload.get("steps", ()), "updated_at": event.created_at}
    )


def _segment_from_row(row: sqlite3.Row) -> ExecutionSegment:
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


def _task_exists(connection: sqlite3.Connection, task_id: TaskId) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM agent_tasks WHERE task_id = ?", (str(task_id),)
        ).fetchone()
        is not None
    )


def _session_exists(connection: sqlite3.Connection, session_id: SessionId) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM session_projections WHERE session_id = ?", (str(session_id),)
        ).fetchone()
        is not None
    )
