"""Scalar Header contracts, explicit maintenance, and actual cold SQL visits."""

import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from agent_storage.task_projection_coverage_cells_schema import (
    initialize_task_replay_privacy,
)
from agent_storage.task_replay_header_schema import (
    backfill_task_replay_headers,
    initialize_task_replay_headers,
)
from agent_storage.task_replay_headers import read_event_header, read_run_header


def header_database(path: Path, task: TaskId, *, install: bool = True):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE session_events (
          event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
          event_type TEXT NOT NULL, payload TEXT NOT NULL, actor TEXT NOT NULL,
          task_id TEXT, task_sequence INTEGER, event_bytes_bound INTEGER,
          UNIQUE(session_id,sequence));
        CREATE UNIQUE INDEX session_events_task_positions ON session_events(task_id,task_sequence);
        CREATE TABLE agent_tasks (task_id TEXT PRIMARY KEY,next_event_sequence INTEGER,
          event_position_state TEXT,namespace TEXT NOT NULL DEFAULT 'local');
        CREATE TABLE execution_segments (session_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,
          event_position_source_cursor INTEGER NOT NULL,
          event_position_source_ready INTEGER NOT NULL);
        CREATE TRIGGER fixture_source_cursor AFTER INSERT ON session_events BEGIN
          INSERT INTO execution_segments VALUES (NEW.session_id,NEW.task_id,NEW.sequence,1)
          ON CONFLICT(session_id) DO UPDATE SET event_position_source_cursor=
            MAX(event_position_source_cursor,excluded.event_position_source_cursor);
        END;
    """)
    connection.execute(
        "INSERT INTO agent_tasks(task_id,next_event_sequence,event_position_state) "
        "VALUES (?,0,'ready')",
        (str(task),),
    )
    connection.commit()
    if install:
        initialize_task_replay_headers(connection)
        initialize_task_replay_privacy(connection)
        connection.commit()
    return connection


def command_body(task: TaskId, sequence: int, kind="run", run="latest", key="public") -> str:
    payload = {} if run is None else {"run_id": run}
    if kind == "message":
        payload["content"] = "hello"
    return json.dumps(
        SessionCommand(
            session_id=SessionId(task),
            kind=SessionCommandKind(kind),
            expected_revision=max(0, sequence - 1),
            idempotency_key=f"{key}{sequence}",
            payload=payload,
        ).event_payload()
    )


def source_row(
    task,
    sequence,
    *,
    kind="run",
    run="latest",
    actor="user",
    key="public",
    body=None,
    source_bytes=1024,
):
    return (
        str(UUID(int=sequence + 1)),
        str(task),
        sequence,
        "session_command_accepted" if body is None else "tool_execution_completed",
        command_body(task, sequence, kind, run, key) if body is None else body,
        actor,
        str(task),
        sequence,
        source_bytes,
    )


INSERT = (
    "INSERT INTO session_events "
    "(event_id,session_id,sequence,event_type,payload,actor,task_id,"
    "task_sequence,event_bytes_bound) VALUES (?,?,?,?,?,?,?,?,?)"
)


def test_real_sqlite_writer_and_explicit_operator_backfill(tmp_path):
    database = tmp_path / "writer.sqlite"
    task = TaskId(uuid4())
    events = SQLiteEventStore(database)
    first = SessionEvent.create(
        session_id=SessionId(task),
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Header"},
    )
    events.append(first)  # Source predates scalar installation.
    SQLiteProjectionStore(database).save_session(rebuild_session([first]))
    store = SQLiteAgentTaskStore(database)
    store.ensure_for_session(SessionId(task))
    with pytest.raises(ValueError, match="headers require explicit backfill"):
        store.read_run_header(task, "latest")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        assert backfill_task_replay_headers(connection, task)
    for n, (kind, run, actor, key) in enumerate(
        (
            ("run", "latest", EventActor.USER, "run"),
            ("resume", None, EventActor.HARNESS, "child-wakeup:"),
            ("resume", None, EventActor.HARNESS, "client-effect-resume:"),
            ("run", None, EventActor.USER, "null"),
        ),
        1,
    ):
        body = json.loads(command_body(task, n, kind, run, key))
        events.append(
            SessionEvent.create(
                session_id=SessionId(task),
                sequence=n,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=actor,
                payload=body,
                idempotency_key=body["idempotency_key"],
            )
        )
    assert store.read_event_header(task, 2).internal_continuation
    assert store.read_event_header(task, 3).internal_continuation
    assert store.read_run_header(task, "latest").stop == 4
    assert store.read_run_header(task, "latest", through_sequence=3).stop is None


def test_install_does_not_decode_legacy_and_byte_budget_resumes_after_reopen(tmp_path):
    path, task = tmp_path / "legacy.sqlite", TaskId(uuid4())
    connection = header_database(path, task, install=False)
    # Non-command payload need not even be parseable by the Header installer.
    connection.executemany(
        INSERT, [source_row(task, n, body="not JSON", source_bytes=512) for n in range(10)]
    )
    connection.execute("UPDATE agent_tasks SET next_event_sequence=10")
    connection.commit()
    connection.create_function("json_type", 2, lambda *_: pytest.fail("legacy JSON parsed"))
    connection.create_function("json_extract", 2, lambda *_: pytest.fail("legacy JSON parsed"))
    initialize_task_replay_headers(connection)
    assert (
        connection.execute("SELECT SUM(replay_header_ready) FROM session_events").fetchone()[0] == 0
    )
    with pytest.raises(ValueError, match="explicit backfill"):
        read_event_header(connection, task, 0)
    assert not backfill_task_replay_headers(connection, task, limit=256, max_bytes=1024)
    connection.commit()
    connection.close()
    with sqlite3.connect(path) as recovered:
        recovered.row_factory = sqlite3.Row
        assert (
            recovered.execute("SELECT SUM(replay_header_ready) FROM session_events").fetchone()[0]
            == 2
        )
        for _ in range(4):
            done = backfill_task_replay_headers(recovered, task, max_bytes=1024)
            recovered.commit()
        assert done and read_event_header(recovered, task, 9).command_kind is None


@pytest.mark.parametrize("size,error", [(None, "byte bounds"), (2_000_000, "byte budget")])
def test_unknown_or_oversized_first_row_is_not_skipped(tmp_path, size, error):
    task = TaskId(uuid4())
    connection = header_database(tmp_path / "blocked.sqlite", task, install=False)
    connection.execute(INSERT, source_row(task, 0, source_bytes=size))
    connection.commit()
    initialize_task_replay_headers(connection)
    with pytest.raises(ValueError, match=error):
        backfill_task_replay_headers(connection, task)
    assert connection.execute("SELECT replay_header_ready FROM session_events").fetchone()[0] == 0
    connection.close()


@pytest.mark.parametrize("external_interrupt", [False, True])
def test_interrupt_or_deadline_keeps_committed_prefix_and_rolls_back_batch(
    tmp_path, external_interrupt
):
    task = TaskId(uuid4())
    connection = header_database(tmp_path / "interrupted.sqlite", task, install=False)
    connection.executemany(INSERT, [source_row(task, n) for n in range(100)])
    connection.commit()
    initialize_task_replay_headers(connection)
    assert not backfill_task_replay_headers(connection, task, limit=2)
    connection.commit()
    connection.create_function("slow_header", 0, lambda: time.sleep(0.003) or 0)
    connection.execute("""CREATE TRIGGER slow_header BEFORE UPDATE OF replay_header_ready
                          ON session_events BEGIN SELECT slow_header(); END""")
    timer = threading.Timer(0.015, connection.interrupt) if external_interrupt else None
    if timer:
        timer.start()
    try:
        with pytest.raises((TimeoutError, sqlite3.OperationalError)):
            backfill_task_replay_headers(
                connection, task, timeout_seconds=2 if external_interrupt else 0.015
            )
    finally:
        if timer:
            timer.cancel()
            timer.join()
    assert (
        connection.execute("SELECT SUM(replay_header_ready) FROM session_events").fetchone()[0] == 2
    )
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    connection.execute("DROP TRIGGER slow_header")
    assert backfill_task_replay_headers(connection, task)
    connection.close()


@pytest.mark.parametrize(
    "arguments",
    [
        dict(limit=True),
        dict(limit=257),
        dict(max_bytes=True),
        dict(max_bytes=1_048_577),
        dict(timeout_seconds=float("nan")),
        dict(timeout_seconds=2.01),
        dict(timeout_seconds=True),
    ],
)
def test_backfill_rejects_unbounded_or_invalid_budget(tmp_path, arguments):
    task = TaskId(uuid4())
    connection = header_database(tmp_path / "budget.sqlite", task)
    with pytest.raises(ValueError):
        backfill_task_replay_headers(connection, task, **arguments)
    connection.close()


def test_readiness_is_distinct_from_invalid_cursor_and_ambiguous_binding(tmp_path):
    task = TaskId(uuid4())
    connection = header_database(tmp_path / "readiness.sqlite", task, install=False)
    connection.execute(INSERT, source_row(task, 0))
    connection.execute("UPDATE agent_tasks SET next_event_sequence=1")
    connection.commit()
    initialize_task_replay_headers(connection)
    initialize_task_replay_privacy(connection)
    connection.commit()
    with pytest.raises(CheckpointNotReady):
        read_event_header(connection, task, 0)
    with pytest.raises(CheckpointNotReady):
        read_run_header(connection, task, "latest", None)
    with pytest.raises(ValueError) as invalid:
        read_event_header(connection, task, True)
    assert not isinstance(invalid.value, CheckpointNotReady)
    assert backfill_task_replay_headers(connection, task)
    connection.execute(INSERT, source_row(task, 1))
    connection.execute("UPDATE agent_tasks SET next_event_sequence=2")
    with pytest.raises(ValueError, match="ambiguous") as ambiguous:
        read_run_header(connection, task, "latest", None)
    assert not isinstance(ambiguous.value, CheckpointNotReady)
    connection.execute("UPDATE agent_tasks SET event_position_state='legacy'")
    with pytest.raises(ValueError) as invalid_run:
        read_run_header(connection, task, "latest", True)
    assert not isinstance(invalid_run.value, CheckpointNotReady)
    with pytest.raises(CheckpointNotReady):
        read_event_header(connection, task, 0)
    with pytest.raises(CheckpointNotReady):
        backfill_task_replay_headers(connection, task)
    connection.close()


def test_header_helpers_preserve_caller_sqlite_snapshot_and_metadata_is_immutable(tmp_path):
    path, task = tmp_path / "snapshot.sqlite", TaskId(uuid4())
    connection = header_database(path, task)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(INSERT, source_row(task, 0))
    connection.execute("UPDATE agent_tasks SET next_event_sequence=1")
    connection.commit()
    connection.execute("BEGIN")
    first = read_run_header(connection, task, "latest", None)
    with sqlite3.connect(path) as writer:
        writer.execute(INSERT, source_row(task, 1, run="next"))
        writer.execute("UPDATE agent_tasks SET next_event_sequence=2")
    assert read_run_header(connection, task, "latest", None) == first
    assert read_event_header(connection, task, 1) is None
    connection.rollback()
    assert read_run_header(connection, task, "latest", None).stop == 1
    for assignment in (
        "replay_run_id='forged'",
        "replay_header_ready=0",
        "payload='{}'",
        "actor='tool'",
        "event_type='session_created'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(f"UPDATE session_events SET {assignment} WHERE task_sequence=0")
    connection.close()


@pytest.mark.parametrize("count", [1_000, 10_000, 100_000])
def test_cold_actual_visits_are_bounded_for_point_and_runstop_with_huge_body(tmp_path, count):
    path, task = tmp_path / "cold.sqlite", TaskId(uuid4())
    connection = header_database(path, task)
    half = count // 2
    rows = (
        source_row(task, n, run=f"run-{n}")
        if n < half
        else source_row(task, n)
        if n == half
        else source_row(task, n, kind="cancel", run="control-only" if n == half + 1 else "latest")
        for n in range(count - 1)
    )
    connection.executemany(INSERT, rows)
    huge = json.dumps({"output": "x" * (8 * 1024 * 1024)})
    connection.execute(INSERT, source_row(task, count - 1, body=huge, source_bytes=len(huge) + 768))
    connection.execute("UPDATE agent_tasks SET next_event_sequence=?", (count,))
    connection.commit()
    connection.close()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.agent_storage.scalar_header_probe",
            "sqlite",
            str(path),
            str(task),
            str(count),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metrics = json.loads(result.stdout)
    assert metrics["decoded_body_bytes"] == 0
    assert metrics["python_vm_steps"] < 800
    for query in metrics["queries"]:
        assert query["fullscan_steps"] == 0
        assert query["visits"] is not None, "real scanstatus required for actual visit evidence"
        assert sum(query["visits"]) <= 2
        assert all(
            ("SEARCH" in node and "SCAN " not in node)
            or node.startswith("CORRELATED SCALAR SUBQUERY ")
            for node in query["plan"]
        ), query
        assert all(
            "COVERING INDEX" in node
            for node in query["plan"]
            if node.startswith("SEARCH session_events ")
        ), query
    print(
        json.dumps(
            {
                "count": count,
                "vm_steps": metrics["python_vm_steps"],
                "max_visits": max(sum(q["visits"]) for q in metrics["queries"]),
                "cold_query_ms": metrics["milliseconds"],
                "sqlite_versions": [
                    metrics["python_sqlite"],
                    metrics["queries"][0]["scanstatus_sqlite"],
                ],
            }
        )
    )
