"""Real read-only/no-body and bounded I/O failure proofs; no app DB or services."""

import socket
import sqlite3
import threading
import time
from contextlib import contextmanager

import psycopg
import pytest
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore
from psycopg import pq, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tests.agent_storage.test_task_projection_work import active
from tests.agent_storage.test_task_projection_work import queue as _queue_fixture
from tests.agent_storage.test_task_projection_work import scratch as _scratch_fixture

queue, scratch = _queue_fixture, _scratch_fixture


def test_huge_payload_readonly_and_explicit_repair_never_decode_body(queue):
    queue.append(0)
    queue.append(1, body='{"blob":"' + "x" * 8_388_608 + '"}')
    store = active(queue)
    if queue.backend == "sqlite":
        original = store._connect

        @contextmanager
        def connect(**kwargs):
            with original(**kwargs) as connection:

                def authorize(action, table, column, *_):
                    if (
                        action == sqlite3.SQLITE_READ
                        and table == "session_events"
                        and column == "payload"
                    ):
                        return sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_FUNCTION and str(column).startswith("json"):
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                connection.set_authorizer(authorize)
                yield connection

        store._connect = connect
    else:
        with queue.connect() as connection:
            schema = conninfo_to_dict(queue.dsn)["options"].split("search_path=")[1].split(",")[0]
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(queue.role)))
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(queue.role)
                )
            )
            for table in (
                "agent_tasks",
                "task_projection_heads",
                "task_projection_work_projectors",
                "task_projection_work_routes",
                "task_projection_work",
            ):
                connection.execute(
                    sql.SQL("GRANT ALL ON {} TO {}").format(
                        sql.Identifier(table), sql.Identifier(queue.role)
                    )
                )
            connection.execute(
                sql.SQL(
                    "GRANT SELECT (deployment_namespace,task_id,task_sequence,"
                    "event_id,event_type,replay_command_kind,replay_run_id,replay_internal_continuation,"
                    "replay_header_ready) ON session_events TO {}"
                ).format(sql.Identifier(queue.role))
            )
            connection.execute(
                sql.SQL("GRANT SELECT ON task_replay_coverage_privacy TO {}").format(
                    sql.Identifier(queue.role)
                )
            )
        configured = conninfo_to_dict(queue.dsn)
        dsn = make_conninfo(queue.dsn, options=configured["options"] + f" -c role={queue.role}")
        store = PostgresTaskProjectionWorkStore(
            PostgresDatabase(dsn, deployment_namespace=queue.namespace), "ag-ui-v1"
        )
    assert not store.repair_projection_work(queue.task).needs_repair
    (work,) = store.read_pending_projection_work()
    assert (work.anchor_sequence, work.requested_through, work.after_sequence) == (0, 1, -1)
    assert store.read_projection_work_problem(work.scope) is None
    with pytest.raises((sqlite3.OperationalError, psycopg.errors.ReadOnlySqlTransaction)):
        with store._connect() as connection:
            connection.execute("UPDATE task_projection_work SET pending=0")
    assert len(store.read_pending_projection_work()) == 1


def test_repair_byte_budget_and_durable_interruption(queue, monkeypatch):
    for n in range(20):
        queue.append(n, body=None if n == 0 else "{}")
    store = active(queue)
    module = (
        "agent_storage.projection_work"
        if queue.backend == "sqlite"
        else "agent_storage.postgres.projection_work"
    )
    monkeypatch.setattr(module + ".MAX_PROJECTION_WORK_BYTES", 400)
    repair = store.repair_projection_work(queue.task)
    assert 0 <= repair.after_sequence < 3 and repair.needs_repair
    cursor = repair.after_sequence
    with queue.connect() as connection:
        if queue.backend == "sqlite":
            connection.execute("""CREATE TRIGGER fixture_interrupt_work
             BEFORE UPDATE OF observed_through
             ON task_projection_work_routes WHEN NEW.observed_through>OLD.observed_through
             BEGIN SELECT RAISE(ABORT,'injected derived-page interruption'); END""")
        else:
            connection.execute("""CREATE FUNCTION fixture_interrupt_work()
             RETURNS trigger AS $$ BEGIN
             IF NEW.observed_through>OLD.observed_through THEN
               RAISE EXCEPTION 'injected derived-page interruption' USING ERRCODE='57014';
             END IF; RETURN NEW; END; $$ LANGUAGE plpgsql""")
            connection.execute("""CREATE TRIGGER fixture_interrupt_work
             BEFORE UPDATE OF observed_through ON task_projection_work_routes
             FOR EACH ROW EXECUTE FUNCTION fixture_interrupt_work()""")
    with pytest.raises((sqlite3.IntegrityError, CheckpointNotReady)):
        queue.store().repair_projection_work(queue.task)
    (pending,) = queue.store().read_projection_work_repairs()
    assert pending.after_sequence == cursor and pending.needs_repair
    with queue.connect() as connection:
        connection.execute(
            "DROP TRIGGER fixture_interrupt_work"
            + (" ON task_projection_work_routes" if queue.backend == "postgres" else "")
        )
    monkeypatch.setattr(module + ".MAX_PROJECTION_WORK_BYTES", 1_048_576)
    assert not queue.store().repair_projection_work(queue.task).needs_repair


def test_unready_positions_remain_durably_discoverable(queue):
    store = active(queue)
    with queue.connect() as connection:
        connection.execute("UPDATE agent_tasks SET event_position_state='assigning'")
    with pytest.raises(CheckpointNotReady, match="position repair"):
        store.repair_projection_work(queue.task)
    (repair,) = queue.store().read_projection_work_repairs()
    assert repair.needs_repair and repair.after_sequence == repair.wanted_through == -1
    with queue.connect() as connection:
        connection.execute("UPDATE agent_tasks SET event_position_state='ready'")
    assert not store.repair_projection_work(queue.task).needs_repair


def test_sqlite_vm_deadline_and_lock_wait(tmp_path, monkeypatch):
    from agent_storage.projection_work import SQLiteTaskProjectionWorkStore

    from tests.agent_storage.projection_work_test_support import QueueFixture

    fixture = QueueFixture("sqlite", tmp_path)
    store = active(fixture)
    monkeypatch.setattr("agent_storage.projection_work.PROJECTION_WORK_SECONDS", 0.05)
    started = time.monotonic()
    with pytest.raises(CheckpointNotReady, match="deadline"):
        with store._connect() as connection:
            connection.execute("""WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL
             SELECT x+1 FROM n WHERE x<100000000) SELECT SUM(x) FROM n""").fetchone()
    assert time.monotonic() - started < 0.5
    with fixture.connect() as owner:
        owner.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            SQLiteTaskProjectionWorkStore(
                fixture.path, "local", "ag-ui-v1"
            ).bootstrap_projection_work()
        assert time.monotonic() - started < 0.5


def test_pg_statement_operation_and_lock_deadlines(scratch, tmp_path, monkeypatch):
    from tests.agent_storage.projection_work_test_support import QueueFixture

    fixture = QueueFixture("postgres", tmp_path, scratch)
    store = active(fixture)
    fixture.append(0)
    (work,) = store.read_pending_projection_work()
    fixture.set_head(work)
    with fixture.connect() as owner:
        owner.execute("SELECT 1 FROM task_projection_work FOR UPDATE")
        started = time.monotonic()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            store.complete_projection_work(work, expected_through=0)
        assert time.monotonic() - started < 0.5
    started = time.monotonic()
    with pytest.raises(CheckpointNotReady, match="deadline"):
        with store._connect() as connection:
            connection.execute("SELECT pg_sleep(10)")
    assert 1.7 < time.monotonic() - started < 3
    started = time.monotonic()
    with pytest.raises(CheckpointNotReady, match="deadline"):
        with store._connect() as connection:
            connection.execute("SELECT pg_sleep(1.3)")
            connection.execute("SELECT pg_sleep(1.3)")
    assert 1.7 < time.monotonic() - started < 2.6  # Remaining operation budget, not 2s each.
    assert len(store.read_pending_projection_work()) == 1


def test_pg_connection_handshake_obeys_shared_task_io_deadline():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    release, accepted = threading.Event(), threading.Event()

    def stall_handshake():
        connection, _ = listener.accept()
        with connection:
            accepted.set()
            release.wait(timeout=4)

    thread = threading.Thread(target=stall_handshake)
    thread.start()
    try:
        database = PostgresDatabase(
            make_conninfo(
                host="127.0.0.1",
                port=listener.getsockname()[1],
                dbname="header_scratch",
                user="postgres",
                sslmode="disable",
            ),
            deployment_namespace="local",
        )
        store = PostgresTaskProjectionWorkStore(database, "ag-ui-v1")
        started = time.monotonic()
        with pytest.raises(CheckpointNotReady, match="deadline"):
            store.read_pending_projection_work()
        elapsed = time.monotonic() - started
        assert accepted.is_set() and 1.7 < elapsed < 3
    finally:
        release.set()
        listener.close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_pg_deadline_commits_completed_prefix_rolls_back_partial_closure_and_cold_resume(
    scratch, tmp_path
):
    from tests.agent_storage.projection_work_test_support import QueueFixture

    fixture = QueueFixture("postgres", tmp_path, scratch)
    fixture.append(0, run="one")
    fixture.append(1, run="two")
    fixture.append(2, body="{}")
    store = active(fixture)
    with fixture.connect() as connection:
        connection.execute("""CREATE FUNCTION fixture_slow_route() RETURNS trigger AS $$ BEGIN
         IF NEW.observed_through=1 THEN PERFORM pg_sleep(1.05); END IF;
         RETURN NEW; END; $$ LANGUAGE plpgsql""")
        connection.execute("""CREATE FUNCTION fixture_slow_closure() RETURNS trigger AS $$ BEGIN
         IF NEW.closed_through IS NOT NULL THEN PERFORM pg_sleep(1.05); END IF;
         RETURN NEW; END; $$ LANGUAGE plpgsql""")
        connection.execute("""CREATE TRIGGER fixture_slow_route
         BEFORE UPDATE OF observed_through ON task_projection_work_routes
         FOR EACH ROW EXECUTE FUNCTION fixture_slow_route()""")
        connection.execute("""CREATE TRIGGER fixture_slow_closure
         BEFORE UPDATE OF closed_through ON task_projection_work
         FOR EACH ROW EXECUTE FUNCTION fixture_slow_closure()""")
    started = time.monotonic()
    first = store.repair_projection_work(fixture.task)
    assert 0 == first.after_sequence < first.wanted_through == 2
    elapsed = time.monotonic() - started
    assert first.needs_repair and 1.5 < elapsed < 2.4
    (pending,) = fixture.store().read_projection_work_repairs()
    assert pending == first
    rows = fixture.work_rows()
    assert len(rows) == 1 and rows[0]["closed_through"] is None
    assert rows[0]["requested_through"] == 0 and rows[0]["revision"] == 1
    with fixture.connect() as connection:
        connection.execute("DROP TRIGGER fixture_slow_route ON task_projection_work_routes")
        connection.execute("DROP TRIGGER fixture_slow_closure ON task_projection_work")
    finished = fixture.store().repair_projection_work(fixture.task)
    assert finished.after_sequence == 2 and not finished.needs_repair
    rows = fixture.work_rows()
    assert [(r["requested_through"], r["closed_through"]) for r in rows] == [(0, 0), (2, None)]
    assert all(r["problem_attempts"] == 0 for r in rows)


@pytest.mark.parametrize("slow_at", [0, 1])
def test_sqlite_vm_deadline_keeps_completed_prefix_and_cold_resume(tmp_path, slow_at):
    from tests.agent_storage.projection_work_test_support import QueueFixture

    fixture = QueueFixture("sqlite", tmp_path)
    fixture.append(0, run="one")
    fixture.append(1, run="two")
    fixture.append(2, body="{}")
    store = active(fixture)
    with fixture.connect() as connection:
        connection.execute(f"""CREATE TRIGGER fixture_slow_route
         BEFORE UPDATE OF observed_through ON task_projection_work_routes
         WHEN NEW.observed_through={slow_at} AND NEW.observed_through>OLD.observed_through
         BEGIN SELECT SUM(x) FROM (WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL
          SELECT x+1 FROM n WHERE x<100000000) SELECT x FROM n); END""")
    started = time.monotonic()
    if slow_at == 0:
        with pytest.raises(CheckpointNotReady, match="deadline"):
            store.repair_projection_work(fixture.task)
    else:
        first = store.repair_projection_work(fixture.task)
        assert first.after_sequence == 0 and first.wanted_through == 2 and first.needs_repair
    assert 1.5 < time.monotonic() - started < 2.5
    (pending,) = fixture.store().read_projection_work_repairs()
    assert pending.after_sequence == slow_at - 1 and pending.needs_repair
    rows = fixture.work_rows()
    assert len(rows) == slow_at
    if slow_at:
        assert rows[0]["closed_through"] is None
        assert rows[0]["requested_through"] == 0 and rows[0]["revision"] == 1
    with fixture.connect() as connection:
        connection.execute("DROP TRIGGER fixture_slow_route")
    finished = fixture.store().repair_projection_work(fixture.task)
    assert finished.after_sequence == 2 and not finished.needs_repair
    rows = fixture.work_rows()
    assert [(r["requested_through"], r["closed_through"]) for r in rows] == [(0, 0), (2, None)]
    assert all(r["problem_attempts"] == 0 for r in rows)


def test_pg_queue_uses_native_task_io_readonly_client_cursor_and_absolute_budget(
    scratch, tmp_path, monkeypatch
):
    from agent_storage.postgres.task_io import TaskIoConnection

    from tests.agent_storage.projection_work_test_support import QueueFixture

    fixture = QueueFixture("postgres", tmp_path, scratch)
    store = active(fixture)
    native_connect = store._database.connect_task_io
    opened, kwargs_seen = [], []

    def connect(**kwargs):
        kwargs_seen.append(kwargs)
        connection = native_connect(**kwargs)
        assert isinstance(connection, TaskIoConnection)
        assert connection.cursor_factory is psycopg.ClientCursor
        opened.append(connection)
        return connection

    monkeypatch.setattr(store._database, "connect_task_io", connect)
    deadline = time.monotonic() + 1
    with store._connect(deadline=deadline) as bounded:
        assert bounded.deadline < deadline
        assert (
            bounded.connection.execute("SHOW transaction_read_only").fetchone()[
                "transaction_read_only"
            ]
            == "on"
        )
    assert kwargs_seen == [{"deadline": deadline, "client_cursor": True}]
    assert opened[0].closed


@pytest.mark.parametrize("committed", [False, True])
def test_pg_unknown_derived_ack_commit_is_reconciled_from_cold_state(
    scratch, tmp_path, monkeypatch, committed
):
    from tests.agent_storage.projection_work_test_support import QueueFixture

    fixture = QueueFixture("postgres", tmp_path, scratch)
    store = active(fixture)
    fixture.append(0)
    (work,) = store.read_pending_projection_work()
    fixture.set_head(work)
    native_connect = store._database.connect_task_io
    opened = []

    def connect(**kwargs):
        connection = native_connect(**kwargs)
        execute = connection.execute

        def lose_commit(statement, params=None):
            if statement != "COMMIT":
                return execute(statement, params)
            if committed:
                execute(statement, params)
            with fixture.connect() as killer:
                assert killer.execute(
                    "SELECT pg_terminate_backend(%s) AS stopped", (connection.info.backend_pid,)
                ).fetchone()["stopped"]
            return execute(statement, params)  # Actual socket failure, never a replayed write.

        connection.execute = lose_commit
        opened.append(connection)
        return connection

    monkeypatch.setattr(store._database, "connect_task_io", connect)
    with pytest.raises(psycopg.OperationalError):
        store.complete_projection_work(work, expected_through=0)
    assert opened[0].closed
    cold = fixture.store()
    pending = cold.read_pending_projection_work()
    assert bool(pending) is not committed
    if pending:
        assert pending[0].scope == work.scope and pending[0].revision == work.revision
        assert pending[0].requested_through == pending[0].after_sequence == 0
        assert cold.complete_projection_work(pending[0], expected_through=0)
    fixture.append(1, body="{}")
    (wake,) = cold.read_pending_projection_work()
    assert wake.requested_through == 1 and wake.revision > work.revision
    assert cold.read_projection_work_problem(wake.scope) is None
    with fixture.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM session_events").fetchone()["n"] == 2


def test_pg_server_50ms_cancellation_before_budget_keeps_connection_and_prefix(scratch, tmp_path):
    from tests.agent_storage.projection_work_test_support import QueueFixture

    fixture = QueueFixture("postgres", tmp_path, scratch)
    store = active(fixture)
    fixture.append(0)
    with store._connect(write=True) as bounded:
        native = bounded.connection
        bounded.execute("UPDATE task_projection_work SET revision=revision+1")
        bounded.execute("SAVEPOINT fixture_statement_budget")
        bounded.execute(
            "UPDATE task_projection_work SET problem_code='integrity',problem_attempts=1"
        )
        native.execute("SET LOCAL statement_timeout='50ms'")
        started = time.monotonic()
        with pytest.raises(psycopg.errors.QueryCanceled) as error:
            native.execute("SELECT pg_sleep(0.5)")
        assert error.value.sqlstate == "57014" and time.monotonic() - started < 0.4
        assert not native.closed and native.pgconn.status == pq.ConnStatus.OK
        assert native.pgconn.transaction_status == pq.TransactionStatus.INERROR
        assert bounded.deadline - time.monotonic() > 0.5
        native.execute("ROLLBACK TO SAVEPOINT fixture_statement_budget")
        bounded.execute("RELEASE SAVEPOINT fixture_statement_budget")
    assert native.closed
    (cold,) = fixture.work_rows()
    assert cold["revision"] == 2 and cold["problem_code"] is None
    assert cold["problem_attempts"] == 0


def test_pg_real_overall_deadline_closes_and_cannot_commit_uncommitted_prefix(scratch, tmp_path):
    from tests.agent_storage.projection_work_test_support import QueueFixture

    fixture = QueueFixture("postgres", tmp_path, scratch)
    store = active(fixture)
    fixture.append(0)
    started = time.monotonic()
    with pytest.raises(CheckpointNotReady, match="deadline"):
        with store._connect(write=True, deadline=started + 0.25) as bounded:
            native = bounded.connection
            bounded.execute("UPDATE task_projection_work SET revision=revision+1")
            native.execute("SET LOCAL statement_timeout='10s'")
            native.execute("SELECT pg_sleep(5)")
    assert native.closed and time.monotonic() - started < 0.75
    with pytest.raises(psycopg.OperationalError):
        native.commit()  # Expiry cannot be bypassed to preserve a desired derived prefix.
    (cold,) = fixture.work_rows()
    assert cold["revision"] == 1 and cold["problem_code"] is None
    assert cold["problem_attempts"] == 0
