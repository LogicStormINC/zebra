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
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_core.ports.task_replay import TaskEventHeader, TaskReadHeader, TaskRunHeader

from agent_storage.database import SQLiteDatabase
from agent_storage.event_rows import deserialize_event_row
from agent_storage.projection_source_metadata import (
    SQLiteProjectionSourceMetadataMixin,
    backfill_projection_source_metadata,
)
from agent_storage.projection_source_metadata_schema import initialize_projection_source_metadata
from agent_storage.projections import SQLiteProjectionStore
from agent_storage.session_handoff_rows import SCHEMA as HANDOFF_SCHEMA
from agent_storage.sqlite import SQLiteEventStore
from agent_storage.task_event_pages import read_task_event_page
from agent_storage.task_event_positions import (
    backfill_task_event_positions,
    initialize_task_positions,
)
from agent_storage.task_projection_checkpoints import SQLiteTaskProjectionCheckpointMixin
from agent_storage.task_projection_coverage_cells_schema import (
    initialize_task_projection_checkpoints,
)
from agent_storage.task_read_summaries import SQLiteTaskReadSummaryMixin
from agent_storage.task_read_summary_schema import task_read_summary_schema
from agent_storage.task_replay_header_schema import (
    backfill_task_replay_headers,
    initialize_task_replay_headers,
)
from agent_storage.task_replay_headers import read_event_header, read_run_header
from agent_storage.worker_progress import WorkerProgressStoreMixin, progress_schema

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


class SQLiteAgentTaskStore(
    SQLiteTaskReadSummaryMixin,
    WorkerProgressStoreMixin,
    SQLiteProjectionSourceMetadataMixin,
    SQLiteTaskProjectionCheckpointMixin,
    AgentTaskPort,
):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        SQLiteEventStore(database_path)
        SQLiteProjectionStore(database_path)
        with self._database.connect() as connection:
            connection.executescript(HANDOFF_SCHEMA)
            connection.executescript(TASK_SCHEMA)
            initialize_task_positions(connection)
            initialize_task_replay_headers(connection)
            initialize_projection_source_metadata(connection)
            initialize_task_projection_checkpoints(connection)
            for statement in progress_schema():
                connection.execute(statement)
            for statement in task_read_summary_schema():
                connection.execute(statement)

    def ensure_for_session(self, session_id: SessionId) -> AgentTask:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task_id = _ensure_task_locked(connection, session_id)
            backfill_task_event_positions(connection, task_id)
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
                backfill_task_event_positions(connection, task_id)
            return len(task_ids)

    def get_task(self, task_id: TaskId) -> AgentTask | None:
        with self._database.connect() as connection:
            if not _task_exists(connection, task_id):
                return None
            return _task_from_connection(connection, task_id)

    def list_tasks(self, *, limit: int) -> tuple[AgentTask, ...]:
        if limit <= 0:
            return ()
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT task_id FROM agent_tasks ORDER BY updated_at DESC, task_id LIMIT ?",
                (limit,),
            ).fetchall()
            return tuple(_task_from_connection(connection, TaskId(UUID(row[0]))) for row in rows)

    def read_task_header(
        self, task_id: TaskId, *, require_source_coverage: bool = False
    ) -> TaskReadHeader | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT t.active_segment_id,t.next_event_sequence,t.event_position_state,"
                "h.title,h.status,h.current_sequence AS active_segment_sequence,"
                "h.title_truncated,h.clarification_id,h.clarification_invalid "
                "FROM agent_tasks t LEFT JOIN session_observation_headers h "
                "ON h.deployment_namespace='' AND h.session_id=t.active_segment_id "
                "WHERE t.task_id=?",
                (str(task_id),),
            ).fetchone()
        if row is None:
            return None
        if row["event_position_state"] != "ready":
            raise CheckpointNotReady("Task Event positions require explicit backfill")
        return TaskReadHeader(
            task_id,
            SessionId(UUID(row["active_segment_id"])),
            row["next_event_sequence"] - 1,
            title=row["title"],
            status=SessionStatus(row["status"]) if row["status"] is not None else None,
            active_segment_sequence=row["active_segment_sequence"],
            title_truncated=bool(row["title_truncated"]),
            clarification_id=row["clarification_id"],
            clarification_invalid=bool(row["clarification_invalid"]),
        )

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

    def task_id_for_session(self, session_id: SessionId) -> TaskId | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT task_id FROM execution_segments WHERE session_id = ?", (str(session_id),)
            ).fetchone()
        return None if row is None else TaskId(UUID(row["task_id"]))

    def is_internal_segment(self, session_id: SessionId) -> bool:
        task_id = self.task_id_for_session(session_id)
        return task_id is not None and task_id != session_id

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
            return _task_from_connection(connection, task_id)

    def read_events(self, task_id: TaskId, after_sequence: int) -> tuple[TaskEvent, ...]:
        if after_sequence < -1:
            raise ValueError("task event cursor must be greater than or equal to -1")
        if self.get_task(task_id) is None:
            return ()
        with self._database.connect() as connection:
            state = connection.execute(
                "SELECT event_position_state FROM agent_tasks WHERE task_id=?", (str(task_id),)
            ).fetchone()
            if state[0] != "ready":
                raise ValueError("Task Event positions require explicit backfill")
            rows = connection.execute(
                """
                SELECT e.task_sequence, e.session_id AS segment_id,
                       e.sequence AS segment_sequence, e.*
                FROM session_events e
                WHERE e.task_id = ? AND e.task_sequence > ?
                ORDER BY e.task_sequence
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

    def backfill_event_positions(self, task_id: TaskId, *, limit: int = 256) -> bool:
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return backfill_task_event_positions(connection, task_id, limit=limit)

    def backfill_replay_headers(
        self,
        task_id: TaskId,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
        timeout_seconds: float = 2.0,
    ) -> bool:
        with self._database.connect() as connection:
            return backfill_task_replay_headers(
                connection,
                task_id,
                limit=limit,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )

    def read_event_page(
        self,
        task_id: TaskId,
        after_sequence: int,
        *,
        limit: int = 256,
        max_bytes: int = 1_048_576,
        through_sequence: int | None = None,
    ) -> TaskEventPage:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            return read_task_event_page(
                connection,
                task_id,
                after_sequence,
                limit=limit,
                max_bytes=max_bytes,
                through=through_sequence,
            )

    def backfill_projection_sources(self, task_id: TaskId, *, limit: int = 256) -> bool:
        """Explicit metadata maintenance, not a side effect of observation."""
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT namespace FROM agent_tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                raise ValueError("projection source Task was not found")
            return backfill_projection_source_metadata(connection, row[0], task_id, limit=limit)

    def read_event_header(self, task_id: TaskId, task_sequence: int) -> TaskEventHeader | None:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            return read_event_header(connection, task_id, task_sequence)

    def read_run_header(
        self,
        task_id: TaskId,
        run_id: str,
        *,
        through_sequence: int | None = None,
    ) -> TaskRunHeader:
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            return read_run_header(connection, task_id, run_id, through_sequence)


def attach_segment_locked(
    connection: sqlite3.Connection,
    *,
    task_id: TaskId,
    segment_id: SessionId,
    predecessor_id: SessionId,
    reason: RolloverReason,
) -> None:
    _ensure_task_locked(connection, predecessor_id)
    if not backfill_task_event_positions(connection, task_id):
        raise ValueError("Task Event positions require explicit backfill before rollover")
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
    foreign = connection.execute(
        """SELECT 1 FROM session_events WHERE session_id=? AND task_id IS NOT NULL
           AND task_id!=? LIMIT 1""",
        (str(segment_id), str(task_id)),
    ).fetchone()
    if foreign is not None:
        raise ValueError("Segment Events already belong to another Task")
    connection.execute(
        """
        INSERT INTO execution_segments
            (session_id,task_id,predecessor_id,segment_index,visibility,rollover_reason)
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
    # ponytail: one adoption batch per transaction. A large existing child stays
    # assigning (new appends fail closed); explicit backfill resumes its frontier.
    backfill_task_event_positions(connection, task_id)


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
    member = connection.execute(
        "SELECT task_id FROM execution_segments WHERE session_id=?", (str(session_id),)
    ).fetchone()
    if member is not None:
        return TaskId(UUID(member[0]))
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
        INSERT INTO agent_tasks
            (task_id,root_session_id,active_segment_id,namespace,created_at,updated_at)
        VALUES (?, ?, ?, 'local', ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            active_segment_id = excluded.active_segment_id,
            updated_at = excluded.updated_at
        """,
        (str(task_id), str(root_id), active_id, root["created_at"], active[0]),
    )
    for row in lineage_values:
        reason = None if row["stage_index"] == 0 else RolloverReason.TERMINAL_FOLLOW_UP.value
        connection.execute(
            """INSERT OR IGNORE INTO execution_segments
                 (session_id,task_id,predecessor_id,segment_index,visibility,rollover_reason)
               VALUES (?, ?, ?, ?, 'internal', ?)""",
            (
                row["session_id"],
                str(task_id),
                row["parent_session_id"],
                row["stage_index"],
                reason,
            ),
        )
    return task_id


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
    current = row["next_event_sequence"] - 1
    return AgentTask(
        task_id=task_id,
        title=row["title"],
        status=SessionStatus(row["status"]),
        active_segment_id=SessionId(UUID(row["active_segment_id"])),
        current_sequence=max(current, row["segment_sequence"]),
        namespace=row["namespace"],
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
