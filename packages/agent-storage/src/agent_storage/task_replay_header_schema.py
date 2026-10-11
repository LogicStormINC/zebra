"""Write-owned scalar replay metadata; installation never hydrates legacy bodies."""

import math
import sqlite3
import time

from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

from agent_storage.database import ensure_column

COLUMNS = (
    "task_id,task_sequence,event_id,session_id,sequence,event_type,"
    "replay_command_kind AS command_kind,replay_run_id AS command_run_id,"
    "replay_internal_continuation AS internal_continuation,replay_header_ready"
)
COMMAND = (
    "replay_header_ready=1 AND event_type='session_command_accepted' "
    "AND replay_internal_continuation=0"
)
EXECUTABLE = f"{COMMAND} AND replay_command_kind IN ('run','resume','message')"
_COVER = (
    "event_id,session_id,sequence,event_type,replay_command_kind,replay_run_id,"
    "replay_internal_continuation,replay_header_ready"
)
HEADER_SCHEMA = f"""
CREATE INDEX IF NOT EXISTS session_events_scalar_header
ON session_events(task_id,task_sequence,{_COVER}) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS session_events_scalar_pending
ON session_events(task_id,task_sequence,event_bytes_bound,replay_header_ready)
WHERE replay_header_ready=0;
CREATE INDEX IF NOT EXISTS session_events_scalar_run_command
ON session_events(task_id,replay_run_id,task_sequence,{_COVER}) WHERE {COMMAND};
CREATE INDEX IF NOT EXISTS session_events_scalar_run_executable
ON session_events(task_id,replay_run_id,task_sequence,{_COVER}) WHERE {EXECUTABLE};
CREATE INDEX IF NOT EXISTS session_events_scalar_executable_order
ON session_events(task_id,task_sequence,replay_header_ready,event_type,
  replay_internal_continuation,replay_command_kind) WHERE {EXECUTABLE};
CREATE INDEX IF NOT EXISTS session_events_scalar_command_order
ON session_events(task_id,task_sequence,replay_header_ready,event_type,
  replay_internal_continuation) WHERE {COMMAND};
"""


def _metadata(prefix: str = "") -> tuple[str, str, str]:
    body, actor, event_type = (f"{prefix}{name}" for name in ("payload", "actor", "event_type"))
    kind = (
        f"CASE WHEN {event_type}='session_command_accepted' THEN CASE "
        f"WHEN json_type({body},'$.kind')='text' THEN json_extract({body},'$.kind') END END"
    )
    run = (
        f"CASE WHEN {event_type}='session_command_accepted' THEN CASE "
        f"WHEN json_type({body},'$.payload.run_id')='text' "
        f"THEN json_extract({body},'$.payload.run_id') END END"
    )
    internal = (
        f"CASE WHEN {event_type}='session_command_accepted' THEN COALESCE("
        f"{actor}='harness' AND ({kind})='resume' AND ({run}) IS NULL AND "
        f"(json_extract({body},'$.idempotency_key') LIKE 'child-wakeup:%' OR "
        f"json_extract({body},'$.idempotency_key') LIKE 'client-effect-resume:%'),0) ELSE 0 END"
    )
    return kind, run, internal


_KIND, _RUN, _INTERNAL = _metadata()
_NEW_KIND, _NEW_RUN, _NEW_INTERNAL = _metadata("NEW.")
_TRIGGERS = f"""
CREATE TRIGGER IF NOT EXISTS session_events_scalar_insert_guard
BEFORE INSERT ON session_events
WHEN NEW.replay_header_ready!=0 OR NEW.replay_command_kind IS NOT NULL
  OR NEW.replay_run_id IS NOT NULL OR NEW.replay_internal_continuation!=0
BEGIN SELECT RAISE(ABORT,'replay metadata is source-owned'); END;
CREATE TRIGGER IF NOT EXISTS session_events_scalar_insert
AFTER INSERT ON session_events BEGIN
  UPDATE session_events SET replay_command_kind=({_KIND}),replay_run_id=({_RUN}),
    replay_internal_continuation=({_INTERNAL}),replay_header_ready=1
    WHERE event_id=NEW.event_id;
END;
CREATE TRIGGER IF NOT EXISTS session_events_scalar_guard
BEFORE UPDATE OF replay_command_kind,replay_run_id,replay_internal_continuation,
  replay_header_ready ON session_events
WHEN NEW.replay_header_ready!=1 OR
  (OLD.replay_header_ready=1 AND (NEW.replay_command_kind IS NOT OLD.replay_command_kind
    OR NEW.replay_run_id IS NOT OLD.replay_run_id
    OR NEW.replay_internal_continuation IS NOT OLD.replay_internal_continuation)) OR
  (OLD.replay_header_ready=0 AND (NEW.replay_command_kind IS NOT ({_NEW_KIND})
    OR NEW.replay_run_id IS NOT ({_NEW_RUN})
    OR NEW.replay_internal_continuation IS NOT ({_NEW_INTERNAL})))
BEGIN SELECT RAISE(ABORT,'replay metadata must match its immutable source'); END;
CREATE TRIGGER IF NOT EXISTS session_events_scalar_source_guard
BEFORE UPDATE OF payload,actor,event_type ON session_events
WHEN OLD.replay_header_ready=1 AND (NEW.payload IS NOT OLD.payload
  OR NEW.actor IS NOT OLD.actor OR NEW.event_type IS NOT OLD.event_type)
BEGIN SELECT RAISE(ABORT,'replay header source is immutable'); END;
"""


def initialize_task_replay_headers(connection: sqlite3.Connection) -> None:
    """Install after Task position columns; no body read or implicit backfill."""
    for name, definition in (
        ("replay_command_kind", "TEXT"),
        ("replay_run_id", "TEXT"),
        (
            "replay_internal_continuation",
            "INTEGER NOT NULL DEFAULT 0 CHECK (replay_internal_continuation IN (0,1))",
        ),
        ("replay_header_ready", "INTEGER NOT NULL DEFAULT 0 CHECK (replay_header_ready IN (0,1))"),
    ):
        ensure_column(connection, "session_events", name, definition)
    connection.executescript(_TRIGGERS + HEADER_SCHEMA)


def validate_header_backfill_budget(limit: int, max_bytes: int, timeout_seconds: float) -> None:
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("replay header backfill limit must be between 1 and 256")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1_048_576:
        raise ValueError("replay header backfill byte budget must be between 1 and 1048576")
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 2
    ):
        raise ValueError("replay header backfill timeout must be greater than 0 and at most 2s")


def backfill_task_replay_headers(
    connection: sqlite3.Connection,
    task_id: TaskId,
    *,
    limit: int = 256,
    max_bytes: int = 1_048_576,
    timeout_seconds: float = 2.0,
) -> bool:
    """One atomic maintenance batch; True means no pending positioned rows.

    Use a dedicated connection/transaction with no caller progress handler.
    Positions and persisted byte bounds must be ready first. No body is read
    to choose the batch; an oversized first row fails instead of being skipped.
    A timeout/interrupt rolls back this maintenance transaction, not previously
    committed batches. Caller commits success; pending index is the continuation.
    Native VM/lock deadlines are not a hard OS scheduling or disk-I/O guarantee.
    """
    validate_header_backfill_budget(limit, max_bytes, timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
    connection.execute(f"PRAGMA busy_timeout={min(busy_timeout, int(timeout_seconds * 1000))}")
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
    try:
        if not connection.in_transaction:
            # Admission and extraction must share one writer snapshot; SQLite
            # must not admit old byte metadata then update a newer source row.
            connection.execute("BEGIN IMMEDIATE")
        task = connection.execute(
            "SELECT event_position_state FROM agent_tasks WHERE task_id=?", (str(task_id),)
        ).fetchone()
        if task is None:
            raise ValueError("Task replay target was not found")
        if task["event_position_state"] != "ready":
            raise CheckpointNotReady("Task Event positions require explicit backfill")
        rows = connection.execute(
            "SELECT rowid,event_bytes_bound FROM session_events "
            "INDEXED BY session_events_scalar_pending WHERE task_id=? AND replay_header_ready=0 "
            "ORDER BY task_sequence LIMIT ?",
            (str(task_id), limit),
        ).fetchall()
        selected: list[int] = []
        total = 0
        for row in rows:
            size = row["event_bytes_bound"]
            if size is None or size <= 0:
                raise CheckpointNotReady("Event byte bounds require explicit backfill")
            if total + size > max_bytes:
                if not selected:
                    raise CheckpointNotReady("Event exceeds replay header backfill byte budget")
                break
            selected.append(row["rowid"])
            total += size
        if selected:
            placeholders = ",".join("?" for _ in selected)
            connection.execute(
                f"UPDATE session_events SET replay_command_kind=({_KIND}),replay_run_id=({_RUN}),"
                f"replay_internal_continuation=({_INTERNAL}),replay_header_ready=1 "
                f"WHERE rowid IN ({placeholders}) AND replay_header_ready=0",
                selected,
            )
        done = (
            connection.execute(
                "SELECT 1 FROM session_events INDEXED BY session_events_scalar_pending "
                "WHERE task_id=? AND replay_header_ready=0 LIMIT 1",
                (str(task_id),),
            ).fetchone()
            is None
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("replay header backfill deadline exceeded")
        return done
    except (sqlite3.OperationalError, TimeoutError) as exc:
        connection.set_progress_handler(None, 0)
        connection.rollback()
        if isinstance(exc, TimeoutError) or time.monotonic() >= deadline:
            raise TimeoutError("replay header backfill deadline exceeded") from exc
        raise
    finally:
        connection.set_progress_handler(None, 0)
        connection.execute(f"PRAGMA busy_timeout={busy_timeout}")
