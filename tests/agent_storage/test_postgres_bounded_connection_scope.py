"""Native callback socket reuse keeps fresh transactions and bounded cancellation."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres import task_io
from agent_storage.postgres.connection_scope import postgres_connection_scope
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_io import TaskIoConnection, TaskIoConnections, task_io_deadline

from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn

native_dsn = checkpoint_dsn


def test_native_bounded_scope_reuses_socket_but_resets_transaction_state(native_dsn):
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    with task_io_deadline(monotonic() + 2), postgres_connection_scope(bounded=True):
        with database.connect_task_io() as first:
            raw = getattr(first, "connection", first)
            first.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            first_pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            first.execute("SET application_name='private-callback-setting'")
        with database.connect() as second:
            assert getattr(second, "connection", second) is raw, "bounded callback opened a socket"
            assert second.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == first_pid
            isolation = second.execute("SHOW transaction_isolation").fetchone()
            assert isolation["transaction_isolation"] == "read committed"
            readonly = second.execute("SHOW transaction_read_only").fetchone()
            assert readonly["transaction_read_only"] == "off"
            assert second.execute("SHOW application_name").fetchone()["application_name"] != (
                "private-callback-setting"
            )
    assert raw.closed


def test_native_reused_connection_sees_independent_commit_and_rolls_back(native_dsn):
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    table = "scope_" + uuid4().hex
    with psycopg.connect(native_dsn) as setup:
        setup.execute(f"CREATE TABLE {table} (value integer)")
        setup.execute(f"INSERT INTO {table} VALUES (1)")
    try:
        with task_io_deadline(monotonic() + 2), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as first:
                assert first.execute(f"SELECT value FROM {table}").fetchone()["value"] == 1
                pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            with psycopg.connect(native_dsn) as independent:
                independent.execute(f"UPDATE {table} SET value=2")
            with database.connect_task_io() as fresh:
                assert fresh.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == pid
                assert fresh.execute(f"SELECT value FROM {table}").fetchone()["value"] == 2
            with pytest.raises(ValueError, match="abort"), database.connect_task_io() as failed:
                failed.execute(f"UPDATE {table} SET value=3")
                raise ValueError("abort")
            with database.connect_task_io() as recovered:
                assert recovered.execute(f"SELECT value FROM {table}").fetchone()["value"] == 2
    finally:
        with psycopg.connect(native_dsn) as cleanup:
            cleanup.execute(f"DROP TABLE {table}")


def test_native_scoped_nested_cursors_and_copied_thread_never_share_active_socket(native_dsn):
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    with task_io_deadline(monotonic() + 2), postgres_connection_scope(bounded=True):
        with database.connect_task_io() as first:
            pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            with database.connect_task_io() as nested:
                assert nested.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != pid
            context = copy_context()

            def probe():
                with database.connect_task_io() as separate:
                    raw = getattr(separate, "connection", separate)
                    assert isinstance(raw, TaskIoConnection)
                    return separate.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]

            with ThreadPoolExecutor(max_workers=1) as executor:
                assert executor.submit(context.run, probe).result() != pid
        with database.connect_task_io(client_cursor=True) as client:
            assert client.cursor_factory is psycopg.ClientCursor
            assert client.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != pid


def test_native_reused_deadline_is_cumulative_and_timed_out_socket_is_discarded(native_dsn):
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    deadline = monotonic() + 0.4
    with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
        with task_io_deadline(deadline), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as first:
                raw = getattr(first, "connection", first)
                first.execute("SELECT pg_sleep(0.22)")
            with task_io_deadline(deadline + 10), database.connect() as second:
                assert getattr(second, "connection", second) is raw
                assert second.deadline == deadline
                second.execute("SELECT pg_sleep(0.22)")
    assert raw.closed and monotonic() < deadline + 0.4


def test_native_unknown_commit_is_not_replayed_and_closes_scope(native_dsn, monkeypatch):
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    commit = TaskIoConnection.commit
    calls = []

    def unknown(connection):
        calls.append(connection)
        commit(connection)
        connection.close()
        raise TimeoutError("ack unknown")

    with task_io_deadline(monotonic() + 2), postgres_connection_scope(bounded=True):
        with monkeypatch.context() as patch:
            patch.setattr(TaskIoConnection, "commit", unknown)
            with pytest.raises(TimeoutError, match="ack unknown"):
                with database.connect_task_io() as connection:
                    connection.execute("SELECT 1")
        assert len(calls) == 1 and calls[0].closed
        with database.connect_task_io() as next_read:
            assert getattr(next_read, "connection", next_read) is not calls[0]
            assert next_read.execute("SELECT 1 AS ready").fetchone()["ready"] == 1


def test_scope_service_configuration_keeps_fresh_connector(monkeypatch):
    connector = TaskIoConnections("service=changing")
    calls = []
    # No server or secret: service expansion must run on each connection attempt.
    def absent(_deadline):
        calls.append(1)
        raise ValueError("fresh service lookup")

    monkeypatch.setattr(connector, "_resolve", absent)
    with task_io_deadline(monotonic() + 2), postgres_connection_scope(bounded=True):
        for _ in range(2):
            with pytest.raises(ValueError, match="fresh service lookup"):
                connector.connect()
    assert len(calls) == 2


def test_native_bounded_scope_ends_inside_longer_callback_and_isolates_environment(
    native_dsn, monkeypatch
):
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    with postgres_connection_scope():
        with task_io_deadline(monotonic() + 2), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as first:
                raw = first.connection
                pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            with monkeypatch.context() as patch:
                patch.setenv("PGAPPNAME", "different-callback-environment")
                with database.connect_task_io() as other:
                    assert other.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != pid
            with database.connect_task_io() as restored:
                assert restored.connection is raw
        assert raw.closed, "bounded socket escaped into a longer callback"


def test_native_scoped_deferred_commit_timeout_does_not_replay_insert(native_dsn):
    with psycopg.connect(native_dsn) as setup:
        setup.execute("CREATE TABLE scope_commit (value integer)")
        setup.execute("""CREATE FUNCTION scope_delay() RETURNS trigger AS $$
          BEGIN PERFORM pg_sleep(3); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        setup.execute("""CREATE CONSTRAINT TRIGGER scope_commit_delay AFTER INSERT
          ON scope_commit DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION scope_delay()""")
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    deadline = monotonic() + 0.4
    with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
        with task_io_deadline(deadline), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as connection:
                raw = connection.connection
                connection.execute("INSERT INTO scope_commit VALUES (1)")
    assert raw.closed and monotonic() < deadline + 0.4
    with psycopg.connect(native_dsn) as verify:
        assert verify.execute("SELECT COUNT(*) FROM scope_commit").fetchone() == (0,)


def test_native_older_libpq_keeps_fresh_server_timeout_connections(native_dsn, monkeypatch):
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    monkeypatch.setattr(task_io.pq, "version", lambda: 160000)
    with task_io_deadline(monotonic() + 2), postgres_connection_scope(bounded=True):
        with database.connect_task_io() as first:
            first_pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        with database.connect_task_io() as second:
            assert second.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != first_pid


@pytest.mark.parametrize("phase", ["query", "commit", "callback"])
def test_native_secondary_close_error_preserves_primary_failure(native_dsn, monkeypatch, phase):
    database = PostgresDatabase(native_dsn, deployment_namespace="bounded-scope")
    close = TaskIoConnection.close

    def broken_close(connection):
        close(connection)
        raise OSError("secondary close")

    def unknown(_connection):
        raise TimeoutError("Task storage commit acknowledgement unknown")

    sockets = []
    with pytest.raises(TimeoutError, match="Task storage"):
        with task_io_deadline(monotonic() + 0.15), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as connection:
                sockets.append(connection.connection)
                monkeypatch.setattr(TaskIoConnection, "close", broken_close)
                if phase == "callback":
                    outstanding = database.connect_task_io()
                    sockets.append(outstanding.connection)
                if phase == "commit":
                    monkeypatch.setattr(TaskIoConnection, "commit", unknown)
                connection.execute("SELECT pg_sleep(1)" if phase == "query" else "SELECT 1")
            if phase == "callback":
                raise TimeoutError("Task storage callback failed")
    assert sockets and all(socket.closed for socket in sockets)
