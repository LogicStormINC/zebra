"""Indexed SQLite command/header queries; no Event body is returned."""

import sqlite3
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionScope,
)
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader

from agent_storage.task_event_page_limits import page_highwater
from agent_storage.task_projection_checkpoint_rows import require_source_member
from agent_storage.task_replay_header_schema import (
    COLUMNS,
    COMMAND,
    EXECUTABLE,
)
from agent_storage.task_replay_header_schema import (
    HEADER_SCHEMA as HEADER_SCHEMA,
)
from agent_storage.task_replay_header_schema import (
    backfill_task_replay_headers as backfill_task_replay_headers,
)


def event_header(row: sqlite3.Row) -> TaskEventHeader:
    if not row["replay_header_ready"]:
        raise CheckpointNotReady("Task replay headers require explicit backfill")
    return TaskEventHeader(
        TaskId(UUID(row["task_id"])),
        row["task_sequence"],
        EventId(UUID(row["event_id"])),
        SessionId(UUID(row["session_id"])),
        row["sequence"],
        EventType(row["event_type"]),
        row["command_kind"] if isinstance(row["command_kind"], str) else None,
        row["command_run_id"],
        bool(row["internal_continuation"]),
    )


def _checked_header(
    connection: sqlite3.Connection, row: sqlite3.Row, task: sqlite3.Row
) -> TaskEventHeader:
    header = event_header(row)
    if header.task_sequence >= task["next_event_sequence"]:
        raise CheckpointConflict("canonical Event header exceeds Task source coverage")
    require_source_member(
        connection,
        ProjectionScope(task["namespace"], header.task_id, None, "source-metadata-v1"),
        row,
        event_id=str(header.event_id),
        segment_id=str(header.segment_id),
        segment_sequence=header.segment_sequence,
    )
    return header


def read_event_header(
    connection: sqlite3.Connection,
    task_id: TaskId,
    sequence: int,
) -> TaskEventHeader | None:
    if type(sequence) is not int or sequence < 0:
        raise ValueError("invalid canonical Event header cursor")
    task = connection.execute(
        "SELECT namespace,next_event_sequence,event_position_state "
        "FROM agent_tasks WHERE task_id=?",
        (str(task_id),),
    ).fetchone()
    if task is None:
        return None
    if task["event_position_state"] != "ready":
        raise CheckpointNotReady("Task Event positions require explicit backfill")
    row = connection.execute(
        f"SELECT {COLUMNS} FROM session_events INDEXED BY session_events_scalar_header "
        "WHERE task_id=? AND task_sequence=?",
        (str(task_id), sequence),
    ).fetchone()
    return None if row is None else _checked_header(connection, row, task)


def read_run_header(
    connection: sqlite3.Connection,
    task_id: TaskId,
    run_id: str,
    through: int | None,
) -> TaskRunHeader:
    if not isinstance(run_id, str) or not run_id or len(run_id) > 256:
        raise ValueError("invalid replay Run identity")
    if through is not None and (type(through) is not int or through < -1):
        raise ValueError("invalid canonical Run highwater")
    bound = "next_event_sequence-1" if through is None else "MIN(next_event_sequence-1,?)"
    bounds = () if through is None else (through, through)
    row = connection.execute(
        "SELECT namespace,next_event_sequence,event_position_state,EXISTS("
        "SELECT 1 FROM task_replay_coverage_privacy INDEXED BY session_events_coverage_privacy "
        "WHERE task_replay_coverage_privacy.task_id=agent_tasks.task_id "
        f"AND task_sequence<={bound}) "
        "AS strict_coverage,EXISTS(SELECT 1 FROM session_events "
        "INDEXED BY session_events_scalar_pending WHERE session_events.task_id=agent_tasks.task_id "
        f"AND task_sequence<={bound} "
        "AND replay_header_ready=0) AS pending_headers "
        "FROM agent_tasks WHERE task_id=?",
        (*bounds, str(task_id)),
    ).fetchone()
    if row is None:
        raise ValueError("Task replay target was not found")
    if row["event_position_state"] != "ready":
        raise CheckpointNotReady("Task Event positions require explicit backfill")
    highwater = page_highwater(-1, row["next_event_sequence"], through)
    if row["pending_headers"]:
        raise CheckpointNotReady("Task replay headers require explicit backfill")
    parameters = str(task_id), run_id, highwater
    strict_coverage = bool(row["strict_coverage"])
    rows = connection.execute(
        f"SELECT {COLUMNS} FROM session_events INDEXED BY session_events_scalar_run_executable "
        "WHERE task_id=? AND replay_run_id=? "
        f"AND task_sequence<=? AND {EXECUTABLE} ORDER BY task_sequence LIMIT 2",
        parameters,
    ).fetchall()
    control_only = not rows
    if not rows:
        rows = connection.execute(
            f"SELECT {COLUMNS} FROM session_events INDEXED BY session_events_scalar_run_command "
            "WHERE task_id=? AND replay_run_id=? "
            f"AND task_sequence<=? AND {COMMAND} ORDER BY task_sequence LIMIT 2",
            parameters,
        ).fetchall()
    if len(rows) > 1:
        raise ValueError("ambiguous canonical Task/run command")
    if not rows:
        exists = connection.execute(
            "SELECT 1 FROM session_events INDEXED BY session_events_scalar_command_order "
            "WHERE task_id=? AND task_sequence<=? "
            f"AND {COMMAND} ORDER BY task_sequence LIMIT 1",
            (str(task_id), highwater),
        ).fetchone()
        return TaskRunHeader(
            task_id,
            run_id,
            highwater,
            None,
            0,
            None,
            legacy=exists is None,
            strict_coverage=strict_coverage,
        )
    anchor = _checked_header(connection, rows[0], row)
    # LIMIT 2 above rejects repeated executable Run IDs. The next executable
    # is therefore the stop; a Run-ID inequality would turn this seek into a scan.
    stop = connection.execute(
        "SELECT task_sequence FROM session_events "
        "INDEXED BY session_events_scalar_executable_order "
        "WHERE task_id=? AND task_sequence>? "
        f"AND task_sequence<=? AND {EXECUTABLE} "
        "ORDER BY task_sequence LIMIT 1",
        (str(task_id), anchor.task_sequence, highwater),
    ).fetchone()
    if stop is not None:
        source = connection.execute(
            f"SELECT {COLUMNS} FROM session_events INDEXED BY session_events_scalar_header "
            "WHERE task_id=? AND task_sequence=?",
            (str(task_id), stop[0]),
        ).fetchone()
        if source is None:
            raise CheckpointConflict("canonical Run stop source is unavailable")
        _checked_header(connection, source, row)
    return TaskRunHeader(
        task_id,
        run_id,
        highwater,
        anchor,
        anchor.task_sequence,
        None if stop is None else stop["task_sequence"],
        control_only=control_only,
        strict_coverage=strict_coverage,
    )


def read_latest_run_header(connection: sqlite3.Connection, task_id: TaskId) -> TaskRunHeader:
    row = connection.execute(
        "SELECT replay_run_id FROM session_events "
        "INDEXED BY session_events_scalar_executable_order "
        f"WHERE task_id=? AND {EXECUTABLE} ORDER BY task_sequence DESC LIMIT 1",
        (str(task_id),),
    ).fetchone()
    if row is None or not isinstance(row[0], str) or not row[0].strip():
        raise CheckpointNotReady("latest executable command requires a canonical Run identity")
    return read_run_header(connection, task_id, row[0], None)
