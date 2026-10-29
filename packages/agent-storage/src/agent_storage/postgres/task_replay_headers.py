"""Namespace-bound indexed PostgreSQL Run metadata, without historical bodies."""

import time
from contextlib import suppress
from typing import Any
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionScope,
)
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader
from psycopg.errors import LockNotAvailable, QueryCanceled

from agent_storage.postgres.task_lineage import PostgresAgentTaskConflictError
from agent_storage.postgres.task_projection_checkpoint_rows import require_source
from agent_storage.postgres.task_replay_scalar_header_migration import (
    SCALAR_COLUMNS,
    SCALAR_COMMAND,
    SCALAR_EXECUTABLE,
)
from agent_storage.task_event_page_limits import page_highwater
from agent_storage.task_replay_header_schema import validate_header_backfill_budget

RUN_ID = (
    "CASE WHEN jsonb_typeof(payload->'payload'->'run_id')='string' "
    "THEN payload->'payload'->>'run_id' END"
)
KIND = "payload->>'kind'"
INTERNAL = (
    f"COALESCE(actor='harness' AND {KIND}='resume' AND ({RUN_ID}) IS NULL "
    "AND (payload->>'idempotency_key' LIKE 'child-wakeup:%' "
    "OR payload->>'idempotency_key' LIKE 'client-effect-resume:%'),false)"
)
COMMAND = f"event_type='session_command_accepted' AND NOT ({INTERNAL})"
EXECUTABLE = f"{COMMAND} AND {KIND} IN ('run','resume','message')"
COLUMNS = (
    "task_id,task_sequence,event_id,session_id,sequence,event_type,"
    f"{KIND} AS command_kind,({RUN_ID}) AS command_run_id,"
    f"({INTERNAL}) AS internal_continuation"
)
HEADER_INDEXES = (
    f"CREATE INDEX session_events_run_command ON session_events"
    f"(deployment_namespace,task_id,({RUN_ID}),task_sequence) WHERE {COMMAND}",
    f"CREATE INDEX session_events_run_executable ON session_events"
    f"(deployment_namespace,task_id,({RUN_ID}),task_sequence) WHERE {EXECUTABLE}",
    f"CREATE INDEX session_events_executable_order ON session_events"
    f"(deployment_namespace,task_id,task_sequence) WHERE {EXECUTABLE}",
    f"CREATE INDEX session_events_command_order ON session_events"
    f"(deployment_namespace,task_id,task_sequence) WHERE {COMMAND}",
)
# Psycopg parses percent signs when parameters are present; DDL stays unchanged
# so registering this query fix does not rewrite a migration checksum.
_QUERY_COLUMNS = SCALAR_COLUMNS.replace("%", "%%")
_QUERY_COMMAND = SCALAR_COMMAND.replace("%", "%%")
_QUERY_EXECUTABLE = SCALAR_EXECUTABLE.replace("%", "%%")


def event_header(row: Any) -> TaskEventHeader:
    if not row["replay_header_ready"]:
        raise CheckpointNotReady("Task replay headers require explicit backfill")
    return TaskEventHeader(
        TaskId(row["task_id"]),
        row["task_sequence"],
        EventId(row["event_id"]),
        SessionId(row["session_id"]),
        row["sequence"],
        EventType(row["event_type"]),
        row["command_kind"],
        row["command_run_id"],
        row["internal_continuation"],
    )


def _checked_header(
    connection: Any, namespace: str, row: Any, next_sequence: int
) -> TaskEventHeader:
    header = event_header(row)
    if header.task_sequence >= next_sequence:
        raise CheckpointConflict("canonical Event header exceeds Task source coverage")
    # ponytail: reuse the canonical source-only guard. This scope's version
    # never addresses a derived checkpoint, and no checkpoint needs to exist.
    require_source(
        connection,
        ProjectionScope(namespace, header.task_id, None, "source-metadata-v1"),
        header.task_sequence,
        event_id=header.event_id,
        segment_id=header.segment_id,
        segment_sequence=header.segment_sequence,
    )
    return header


def read_event_header(
    connection: Any,
    namespace: str,
    task_id: TaskId,
    sequence: int,
) -> TaskEventHeader | None:
    if type(sequence) is not int or sequence < 0:
        raise ValueError("invalid canonical Event header cursor")
    task = connection.execute(
        "SELECT next_event_sequence,event_position_state FROM agent_tasks "
        "WHERE deployment_namespace=%s AND task_id=%s",
        (namespace, task_id),
    ).fetchone()
    if task is None:
        return None
    if task["event_position_state"] != "ready":
        raise CheckpointNotReady("Task Event positions require explicit backfill")
    row = connection.execute(
        f"SELECT {_QUERY_COLUMNS} FROM session_events "
        "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=%s",
        (namespace, task_id, sequence),
    ).fetchone()
    return (
        None
        if row is None
        else _checked_header(connection, namespace, row, task["next_event_sequence"])
    )


def read_event_header_by_key(
    connection: Any, namespace: str, task_id: TaskId, segment_id: SessionId, key: str
) -> TaskEventHeader | None:
    if not isinstance(key, str) or not key or len(key) > 1024:
        raise ValueError("invalid native Event idempotency key")
    task = connection.execute(
        "SELECT next_event_sequence,event_position_state FROM agent_tasks "
        "WHERE deployment_namespace=%s AND task_id=%s",
        (namespace, task_id),
    ).fetchone()
    if task is None:
        return None
    if task["event_position_state"] != "ready":
        raise CheckpointNotReady("Task Event positions require explicit backfill")
    row = connection.execute(
        f"SELECT {_QUERY_COLUMNS} FROM session_events WHERE deployment_namespace=%s "
        "AND session_id=%s AND idempotency_key=%s AND task_id=%s",
        (namespace, segment_id, key, task_id),
    ).fetchone()
    return (
        None
        if row is None
        else _checked_header(connection, namespace, row, task["next_event_sequence"])
    )


RUN_HEADER_BODY = f"""task AS (SELECT t.next_event_sequence,t.event_position_state,
          LEAST(t.next_event_sequence-1,COALESCE(a.through,t.next_event_sequence-1)) AS highwater
          FROM agent_tasks t,args a WHERE t.deployment_namespace=a.ns AND t.task_id=a.tid),
        executable AS (SELECT {_QUERY_COLUMNS} FROM session_events
          WHERE deployment_namespace=(SELECT ns FROM args) AND task_id=(SELECT tid FROM args)
          AND replay_run_id=(SELECT rid FROM args)
          AND task_sequence<=(SELECT highwater FROM task) AND {_QUERY_EXECUTABLE}
          ORDER BY task_sequence LIMIT 2),
        control AS (SELECT {_QUERY_COLUMNS} FROM session_events
          WHERE deployment_namespace=(SELECT ns FROM args) AND task_id=(SELECT tid FROM args)
          AND replay_run_id=(SELECT rid FROM args)
          AND task_sequence<=(SELECT highwater FROM task)
          AND {_QUERY_COMMAND}
          AND NOT EXISTS(SELECT 1 FROM executable) ORDER BY task_sequence LIMIT 2),
        anchor AS (SELECT * FROM executable UNION ALL SELECT * FROM control),
        stop_position AS (SELECT task_sequence FROM session_events
          WHERE deployment_namespace=(SELECT ns FROM args) AND task_id=(SELECT tid FROM args)
          AND task_sequence>(SELECT min(task_sequence) FROM anchor)
          AND task_sequence<=(SELECT highwater FROM task) AND {_QUERY_EXECUTABLE}
          ORDER BY task_sequence LIMIT 1),
        stop AS (SELECT {_QUERY_COLUMNS} FROM session_events
          WHERE deployment_namespace=(SELECT ns FROM args) AND task_id=(SELECT tid FROM args)
          AND task_sequence=(SELECT task_sequence FROM stop_position)),
        checked AS (SELECT c.event_id,m.task_id AS member_task,m.event_position_source_ready,
          m.event_position_source_cursor,c.sequence FROM (SELECT * FROM anchor UNION ALL
          SELECT * FROM stop) c LEFT JOIN execution_segments m
          ON m.deployment_namespace=(SELECT ns FROM args) AND m.session_id=c.session_id)
        SELECT t.*,EXISTS(SELECT 1 FROM task_replay_coverage_privacy e
          WHERE deployment_namespace=(SELECT ns FROM args) AND task_id=(SELECT tid FROM args)
          AND task_sequence<=(SELECT highwater FROM task)) AS strict_coverage,
          EXISTS(SELECT 1 FROM session_events WHERE deployment_namespace=(SELECT ns FROM args)
          AND task_id=(SELECT tid FROM args) AND task_sequence<=(SELECT highwater FROM task)
          AND NOT replay_header_ready) AS pending,
          (SELECT jsonb_agg(to_jsonb(c) ORDER BY task_sequence) FROM anchor c) AS commands,
          EXISTS(SELECT 1 FROM executable) AS executable,
          (SELECT task_sequence FROM session_events WHERE deployment_namespace=(SELECT ns FROM args)
          AND task_id=(SELECT tid FROM args) AND task_sequence<=(SELECT highwater FROM task)
          AND {_QUERY_COMMAND}
          ORDER BY task_sequence LIMIT 1) AS first_command,
          (SELECT to_jsonb(c) FROM stop c) AS stop,
          (SELECT jsonb_agg(to_jsonb(c)) FROM checked c) AS checked
          FROM task t"""


def read_run_header(
    connection: Any,
    namespace: str,
    task_id: TaskId,
    run_id: str,
    through: int | None,
) -> TaskRunHeader:
    if not isinstance(run_id, str) or not run_id or len(run_id) > 256:
        raise ValueError("invalid replay Run identity")
    if through is not None and (type(through) is not int or through < -1):
        raise ValueError("invalid canonical Run highwater")
    row = connection.execute(
        "SELECT * FROM (WITH args AS (SELECT %s::text ns,%s::uuid tid,"
        "%s::text rid,%s::bigint through)," + RUN_HEADER_BODY + ") metadata",
        (namespace, task_id, run_id, through),
    ).fetchone()
    return run_header_from_row(row, task_id, run_id, through)


def run_header_from_row(
    row: Any, task_id: TaskId, run_id: str, through: int | None = None
) -> TaskRunHeader:
    if row is None:
        raise PostgresAgentTaskConflictError("Task replay target was not found")
    if row["event_position_state"] != "ready":
        raise CheckpointNotReady("Task Event positions require explicit backfill")
    highwater = page_highwater(-1, row["next_event_sequence"], through)
    if row["pending"]:
        raise CheckpointNotReady("Task replay headers require explicit backfill")
    commands = row["commands"] or []
    if len(commands) > 1:
        raise PostgresAgentTaskConflictError("ambiguous canonical Task/run command")
    if any(
        item["member_task"] != str(task_id)
        or not item["event_position_source_ready"]
        or item["sequence"] > item["event_position_source_cursor"]
        for item in row["checked"] or []
    ):
        raise CheckpointConflict("checkpoint locator conflicts with canonical source")
    anchor = json_event_header(commands[0]) if commands else None
    stop = json_event_header(row["stop"]) if row["stop"] is not None else None
    return TaskRunHeader(
        task_id,
        run_id,
        highwater,
        anchor,
        anchor.task_sequence if anchor else 0,
        stop.task_sequence if stop else None,
        legacy=row["first_command"] is None,
        control_only=bool(anchor and not row["executable"]),
        strict_coverage=row["strict_coverage"],
    )


def json_event_header(row: Any) -> TaskEventHeader:
    return event_header(
        {
            **row,
            "task_id": UUID(row["task_id"]),
            "event_id": UUID(row["event_id"]),
            "session_id": UUID(row["session_id"]),
        }
    )


def read_latest_run_header(connection: Any, namespace: str, task_id: TaskId) -> TaskRunHeader:
    # ponytail: select identity and metadata in one statement snapshot. Reuse the
    # explicit-Run source checks, never cache a previously current Run.
    row = connection.execute(
        "WITH latest AS (SELECT replay_run_id FROM session_events "
        f"WHERE deployment_namespace=%s AND task_id=%s AND {_QUERY_EXECUTABLE} "
        "ORDER BY task_sequence DESC LIMIT 1),"
        "args AS (SELECT %s::text ns,%s::uuid tid,replay_run_id rid,"
        "NULL::bigint through FROM latest) "
        "SELECT a.rid AS latest_run_id,metadata.* FROM args a "
        "LEFT JOIN LATERAL (WITH " + RUN_HEADER_BODY + ") metadata ON true",
        (namespace, task_id, namespace, task_id),
    ).fetchone()
    if row is None or not isinstance(row["latest_run_id"], str) or not row["latest_run_id"].strip():
        raise CheckpointNotReady("latest executable command requires a canonical Run identity")
    if len(row["latest_run_id"]) > 256:
        raise ValueError("invalid replay Run identity")
    return run_header_from_row(
        row if row["next_event_sequence"] is not None else None, task_id, row["latest_run_id"]
    )


def backfill_task_replay_headers(
    connection: Any,
    namespace: str,
    task_id: TaskId,
    *,
    limit: int = 256,
    max_bytes: int = 1_048_576,
    timeout_seconds: float = 2.0,
) -> bool:
    """One atomic maintenance batch; caller commits, True means done.

    Requires a dedicated non-autocommit connection. Positions/byte bounds first;
    no body reads to choose the batch. Timeout/cancel rolls back the savepoint.
    Statement/lock deadlines do not promise a hard network/OS scheduling ceiling.
    """
    validate_header_backfill_budget(limit, max_bytes, timeout_seconds)
    if connection.autocommit:
        raise ValueError("replay header backfill requires a caller-owned transaction")
    deadline = time.monotonic() + timeout_seconds

    def remaining() -> None:
        milliseconds = int((deadline - time.monotonic()) * 1000)
        if milliseconds <= 0:
            raise TimeoutError("replay header backfill deadline exceeded")
        connection.execute(
            "SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
            (f"{milliseconds}ms", f"{milliseconds}ms"),
        )

    # SAVEPOINT starts a non-autocommit transaction if needed; success does not
    # commit the caller's transaction. Rollback restores transaction-local GUCs.
    connection.execute("SAVEPOINT scalar_header_backfill")
    try:
        previous = connection.execute(
            "SELECT current_setting('statement_timeout') AS statement_timeout,"
            "current_setting('lock_timeout') AS lock_timeout"
        ).fetchone()
        remaining()
        task = connection.execute(
            "SELECT event_position_state FROM agent_tasks "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (namespace, task_id),
        ).fetchone()
        if task is None:
            raise PostgresAgentTaskConflictError("Task replay target was not found")
        if task["event_position_state"] != "ready":
            raise CheckpointNotReady("Task Event positions require explicit backfill")
        remaining()
        rows = connection.execute(
            "SELECT event_id,event_bytes_bound FROM session_events "
            "WHERE deployment_namespace=%s AND task_id=%s AND NOT replay_header_ready "
            "ORDER BY task_sequence LIMIT %s",
            (namespace, task_id, limit),
        ).fetchall()
        total = 0
        selected: list[UUID] = []
        for row in rows:
            size = row["event_bytes_bound"]
            if size is None or size <= 0:
                raise CheckpointNotReady("Event byte bounds require explicit backfill")
            if total + size > max_bytes:
                if not selected:
                    raise CheckpointNotReady("Event exceeds replay header backfill byte budget")
                break
            selected.append(row["event_id"])
            total += size
        for event_id in selected:
            remaining()
            # Point updates avoid a hash join/full-source scan chosen for a
            # bulk UPDATE, and never acquire Task-position locks in reverse.
            connection.execute(
                "UPDATE session_events SET replay_header_ready=true "
                "WHERE deployment_namespace=%s AND event_id=%s AND NOT replay_header_ready",
                (namespace, event_id),
            )
        remaining()
        done = (
            connection.execute(
                "SELECT 1 FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
                "AND NOT replay_header_ready LIMIT 1",
                (namespace, task_id),
            ).fetchone()
            is None
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("replay header backfill deadline exceeded")
        connection.execute(
            "SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
            (previous["statement_timeout"], previous["lock_timeout"]),
        )
    except BaseException as exc:
        # Actual I/O cancellation may have closed the connection. Secondary
        # rollback failure must not replace the original deadline/integrity error.
        with suppress(Exception):
            connection.execute("ROLLBACK TO SAVEPOINT scalar_header_backfill")
            connection.execute("RELEASE SAVEPOINT scalar_header_backfill")
        if isinstance(exc, QueryCanceled | LockNotAvailable):
            raise TimeoutError("replay header backfill deadline exceeded or cancelled") from exc
        raise
    connection.execute("RELEASE SAVEPOINT scalar_header_backfill")
    return done
