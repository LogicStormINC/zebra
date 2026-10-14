"""Real source allocation plus metadata67 plus queue68, with no facade edits."""

import json
import os
import sqlite3
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore
from agent_storage.postgres.projection_work_fanout_migration import (
    TASK_PROJECTION_WORK_FANOUT_MIGRATION,
)
from agent_storage.postgres.projection_work_migration import TASK_PROJECTION_WORK_MIGRATION
from agent_storage.postgres.projection_work_routing_migration import (
    TASK_PROJECTION_WORK_ROUTING_MIGRATION,
)
from agent_storage.postgres.task_replay_coverage_privacy_migration import (
    TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION,
)
from agent_storage.projection_source_metadata_schema import initialize_projection_source_metadata
from agent_storage.projection_work import SQLiteTaskProjectionWorkStore
from agent_storage.projection_work_schema import initialize_projection_work
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from tests.agent_storage.test_postgres_projection_source_metadata import NS, seed
from tests.agent_storage.test_scalar_task_replay_headers import command_body


def test_migration_68_frozen_checksum():
    assert TASK_PROJECTION_WORK_MIGRATION.version == 68
    assert TASK_PROJECTION_WORK_MIGRATION.checksum == (
        "a08e29f23387b57b0ed740702c65bedee740384226363e3d919f7689dc36201f"
    )


def transient_failures(store, monkeypatch, count):
    clock = [10_000.0]
    monkeypatch.setattr("agent_storage.projection_work.time.time", lambda: clock[0])
    for attempt in range(1, count + 1):
        (work,) = store.read_pending_projection_work()
        assert store.defer_projection_work(
            work, problem_code="projection_failed", retry_after_seconds=1
        )
        assert store.read_projection_work_problem(work.scope).attempts == attempt
        clock[0] += 2
        assert store.retry_due_projection_work() == 1


def failure_count(store, scope):
    query = (
        "SELECT problem_attempts FROM task_projection_work WHERE deployment_namespace=? "
        "AND task_id=? AND anchor_key=? AND projector_version=?"
    )
    if isinstance(store, PostgresTaskProjectionWorkStore):
        query = query.replace("?", "%s")
    with store._connect() as connection:
        return connection.execute(
            query,
            (
                scope.namespace,
                str(scope.task_id),
                str(scope.anchor_event_id),
                scope.projector_version,
            ),
        ).fetchone()["problem_attempts"]


@pytest.fixture
def native_dsn():
    configured = os.environ.get("ZEBRA_HEADER_SCRATCH_DSN")
    if not configured:
        pytest.skip("set ZEBRA_HEADER_SCRATCH_DSN to the existing isolated scratch server")
    settings = conninfo_to_dict(configured)
    assert settings.get("dbname") == "header_scratch"
    assert settings.get("host") in ("localhost", "127.0.0.1")
    schema = f"projection_work_native_{uuid4().hex}"
    with psycopg.connect(configured, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(configured, options=f"-c search_path={schema},public")
    try:
        with psycopg.connect(dsn) as connection:
            for migration in sorted(MIGRATIONS, key=lambda m: m.version):
                if migration.version <= 67:
                    for statement in migration.statements:
                        connection.execute(statement)
            for statement in TASK_PROJECTION_WORK_MIGRATION.statements:
                connection.execute(statement)
        yield dsn
    finally:
        with psycopg.connect(configured, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.parametrize("prior_failures", [0, 7])
def test_sqlite_actual_allocator_header_metadata_and_queue(tmp_path, monkeypatch, prior_failures):
    path = tmp_path / "native.sqlite"
    session = SessionId(uuid4())
    events = SQLiteEventStore(path)
    first = SessionEvent.create(
        session_id=session,
        sequence=0,
        actor=EventActor.SYSTEM,
        event_type=EventType.SESSION_CREATED,
        payload={"title": "Queue"},
    )
    events.append(first)
    SQLiteProjectionStore(path).save_session(rebuild_session([first]))
    tasks = SQLiteAgentTaskStore(path)
    task = tasks.ensure_for_session(session).task_id
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        initialize_projection_source_metadata(connection)
        initialize_projection_work(connection)
    while not tasks.backfill_replay_headers(task):
        pass
    store = SQLiteTaskProjectionWorkStore(path, "local", "ag-ui-v1")
    store.enable_projection_work()
    assert not store.repair_projection_work(task).needs_repair
    for n in range(1, 6):
        command = n in (1, 4)
        events.append(
            SessionEvent.create(
                session_id=session,
                sequence=n,
                actor=EventActor.USER if command else EventActor.SYSTEM,
                event_type=EventType.SESSION_COMMAND_ACCEPTED
                if command
                else EventType.SESSION_TITLE_UPDATED,
                payload=json.loads(command_body(task, n, run=f"run-{n}"))
                if command
                else {"title": "next"},
            )
        )
        if n in (1, 3):
            if n == 1:
                transient_failures(store, monkeypatch, prior_failures)
            (waiting,) = store.read_pending_projection_work()
            assert store.defer_projection_work(waiting, problem_code="not_ready")
            assert (
                SQLiteTaskProjectionWorkStore(
                    path, "local", "ag-ui-v1"
                ).read_pending_projection_work()
                == ()
            )
        elif n in (2, 4):
            assert store.read_projection_work_problem(waiting.scope) is None, (
                "admission wait retained a prior transient failure cap after canonical source wake"
            )
            assert failure_count(store, waiting.scope) == prior_failures
            assert store.read_pending_projection_work()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT task_sequence FROM session_events ORDER BY sequence"
        ).fetchall() == [(n,) for n in range(6)]
        assert (
            connection.execute(
                "SELECT through_sequence FROM task_projection_source_heads"
            ).fetchone()[0]
            == 5
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM session_events WHERE replay_header_ready=1 "
                "AND projection_block_start IS NOT NULL"
            ).fetchone()[0]
            == 6
        )
    jobs = sorted(store.read_pending_projection_work(), key=lambda w: w.anchor_sequence)
    assert [(w.anchor_sequence, w.requested_through, w.closed_through) for w in jobs] == [
        (1, 3, 3),
        (4, 5, None),
    ]


@pytest.mark.parametrize("prior_failures", [0, 7])
def test_pg_deferred_allocator_revisited_segments_and_queue(
    native_dsn, monkeypatch, prior_failures
):
    with psycopg.connect(native_dsn, row_factory=dict_row) as connection:
        task, a, b = seed(connection)
    store = PostgresTaskProjectionWorkStore(
        PostgresDatabase(native_dsn, deployment_namespace=NS), "ag-ui-v1"
    )
    store.enable_projection_work()
    visits = ((a, 0, "run"), (a, 1, None), (b, 0, "internal"), (b, 1, None), (a, 2, "message"))
    with psycopg.connect(native_dsn, row_factory=dict_row) as connection:
        for position, (segment, sequence, kind) in enumerate(visits):
            command = kind is not None
            body = (
                json.loads(
                    command_body(
                        TaskId(segment),
                        sequence,
                        kind="resume" if kind == "internal" else kind,
                        run=None if kind == "internal" else f"run-{position}",
                        key="child-wakeup:" if kind == "internal" else "public",
                    )
                )
                if command
                else {"title": "receipt"}
            )
            connection.execute(
                "INSERT INTO session_events(deployment_namespace,event_id,session_id,"
                "sequence,event_type,payload,actor,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,now())",
                (
                    NS,
                    uuid4(),
                    segment,
                    sequence,
                    "session_command_accepted" if command else "session_title_updated",
                    json.dumps(body),
                    "harness" if kind == "internal" else "user",
                ),
            )
            connection.commit()  # Native deferred allocator, never assigned Task coordinates here.
            if position in (0, 3):
                if position == 0:
                    transient_failures(store, monkeypatch, prior_failures)
                (waiting,) = store.read_pending_projection_work()
                assert store.defer_projection_work(waiting, problem_code="not_ready")
                assert (
                    PostgresTaskProjectionWorkStore(
                        PostgresDatabase(native_dsn, deployment_namespace=NS), "ag-ui-v1"
                    ).read_pending_projection_work()
                    == ()
                )
            elif position in (1, 4):
                assert store.read_projection_work_problem(waiting.scope) is None, (
                    "admission wait retained a prior transient failure cap "
                    "after canonical source wake"
                )
                assert failure_count(store, waiting.scope) == prior_failures
                assert store.read_pending_projection_work()
        assert [
            r["task_sequence"]
            for r in connection.execute(
                "SELECT task_sequence FROM session_events ORDER BY task_sequence"
            ).fetchall()
        ] == list(range(5))
        assert (
            connection.execute(
                "SELECT through_sequence FROM task_projection_source_heads"
            ).fetchone()["through_sequence"]
            == 4
        )
        blocks = connection.execute(
            "SELECT first_task_sequence,last_task_sequence FROM task_projection_blocks "
            "ORDER BY first_task_sequence"
        ).fetchall()
        assert [(r["first_task_sequence"], r["last_task_sequence"]) for r in blocks] == [
            (0, 1),
            (2, 3),
            (4, 4),
        ]
    jobs = sorted(store.read_pending_projection_work(), key=lambda w: w.anchor_sequence)
    assert [(w.anchor_sequence, w.requested_through, w.closed_through) for w in jobs] == [
        (0, 3, 3),
        (4, 4, None),
    ]


@pytest.mark.parametrize("reenable", [False, True])
def test_pg_bootstrap_does_not_lose_existing_task_append_across_enable(native_dsn, reenable):
    with psycopg.connect(native_dsn, row_factory=dict_row) as connection:
        assert connection.execute("SELECT current_schema() AS s").fetchone()["s"].startswith(
            "projection_work_native_"
        )
        for migration in (
            TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION, TASK_PROJECTION_WORK_ROUTING_MIGRATION,
            TASK_PROJECTION_WORK_FANOUT_MIGRATION,
        ):
            for statement in migration.statements:
                connection.execute(statement)
        task, segment, _ = seed(connection)
    database = PostgresDatabase(native_dsn, deployment_namespace=NS)
    store = PostgresTaskProjectionWorkStore(database, "ag-ui-v1")
    if reenable:
        store.enable_projection_work()
        assert store.bootstrap_projection_work()
        assert not store.repair_projection_work(task).needs_repair
        store.disable_projection_work()
    with psycopg.connect(native_dsn, row_factory=dict_row) as source:
        source.execute(
            "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,"
            "event_type,payload,actor,created_at) VALUES (%s,%s,%s,0,%s,%s,'user',now())",
            (
                NS,
                uuid4(),
                segment,
                "session_command_accepted",
                command_body(task, 0, run="in-flight"),
            ),
        )
        # Run the real deferred allocator while disabled, retaining its uncommitted HWM.
        source.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert (
            source.execute(
                "SELECT task_sequence FROM session_events WHERE deployment_namespace=%s "
                "AND session_id=%s AND sequence=0",
                (NS, segment),
            ).fetchone()["task_sequence"]
            == 0
        )
        store.enable_projection_work()
        try:
            store.bootstrap_projection_work()
        except psycopg.errors.LockNotAvailable:
            pass  # A bounded retry is valid; closing discovery with the old HWM is not.
        source.commit()
    cold = PostgresTaskProjectionWorkStore(database, "ag-ui-v1")
    assert cold.bootstrap_projection_work()
    (repair,) = cold.read_projection_work_repairs()
    assert repair.wanted_through == 0, "enabled bootstrap lost a committed native append"
    assert not cold.repair_projection_work(task).needs_repair
    (work,) = cold.read_pending_projection_work()
    assert work.run_id == "in-flight" and work.requested_through == 0
    assert cold.read_projection_work_problem(work.scope) is None
