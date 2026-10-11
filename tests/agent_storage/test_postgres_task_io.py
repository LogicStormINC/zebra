"""Native Task I/O deadlines, including DNS children and COMMIT, on scratch PG."""

from __future__ import annotations

import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres import task_io
from agent_storage.postgres.database import PostgresDatabase
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tests.agent_storage.test_postgres_scalar_task_replay_headers import scratch as _scratch_fixture

scratch = _scratch_fixture


def test_request_scope_bounds_ordinary_store_connections(scratch: tuple[str, str]) -> None:
    dsn, _ = scratch
    database = PostgresDatabase(dsn, deployment_namespace="task-io")
    deadline = time.monotonic() + 0.35
    connections = []
    with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
        with task_io.task_io_deadline(deadline):
            for _ in range(2):
                with database.connect() as connection:
                    assert isinstance(connection, task_io.TaskIoConnection)
                    assert connection.deadline == deadline
                    connections.append(connection)
                    connection.execute("SELECT pg_sleep(0.22)")
    assert time.monotonic() < deadline + 0.45
    assert all(connection.closed for connection in connections)
    with database.connect() as ordinary:
        assert not isinstance(ordinary, task_io.TaskIoConnection)
        assert ordinary.execute("SHOW statement_timeout").fetchone() == {"statement_timeout": "0"}


def test_request_scope_bounds_independent_connections_and_resets(scratch: tuple[str, str]) -> None:
    dsn, _ = scratch
    database = PostgresDatabase(dsn, deployment_namespace="task-io")
    started = time.monotonic()
    deadline = started + 0.35
    connections = []
    with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
        with task_io.task_io_deadline(deadline):
            with database.connect_task_io() as first:
                assert isinstance(first, task_io.TaskIoConnection)
                connections.append(first)
                first.execute("SELECT pg_sleep(0.22)")
            with task_io.task_io_deadline(deadline + 10):
                with database.connect_task_io() as second:
                    assert isinstance(second, task_io.TaskIoConnection)
                    connections.append(second)
                    assert second.deadline == first.deadline == deadline
                    second.execute("SELECT pg_sleep(0.22)")
    assert time.monotonic() - started < 0.8
    assert all(connection.closed for connection in connections)
    with database.connect_task_io() as reset:
        assert isinstance(reset, task_io.TaskIoConnection)
        assert reset.deadline > deadline
        assert reset.execute("SELECT 1 AS ready").fetchone() == {"ready": 1}


def test_connection_and_statements_share_one_deadline(scratch: tuple[str, str]) -> None:
    dsn, _ = scratch
    database = PostgresDatabase(dsn, deployment_namespace="task-io")
    started = time.monotonic()
    connection = database.connect_task_io(timeout_seconds=0.4)
    with pytest.raises(TimeoutError, match="Task storage"):
        with connection:
            connection.execute("SELECT pg_sleep(0.2)")
            connection.execute("SELECT pg_sleep(0.2)")
    assert connection.closed
    assert time.monotonic() - started < 0.8
    # Ordinary stores retain their existing semantics; the limit is opt-in.
    with database.connect() as ordinary:
        ordinary.execute("SELECT pg_sleep(0.45)")


def test_actual_connect_handshake_is_bounded_without_orphan_thread() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        ended = threading.Event()

        def stalled_peer() -> None:
            with server.accept()[0] as accepted:
                accepted.settimeout(2)
                while accepted.recv(65536):
                    pass
            ended.set()

        peer = threading.Thread(target=stalled_peer, daemon=True)
        peer.start()
        database = PostgresDatabase(
            make_conninfo(host="127.0.0.1", port=server.getsockname()[1], sslmode="disable"),
            deployment_namespace="task-io",
        )
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="Task storage"):
            database.connect_task_io(timeout_seconds=0.25)
        assert time.monotonic() - started < 0.6
        assert ended.wait(0.5), "libpq connect socket survived its deadline"
        peer.join(0.5)
        assert not peer.is_alive()


def test_deferred_commit_is_cancelled_and_rolled_back(scratch: tuple[str, str]) -> None:
    dsn, _ = scratch
    label = f"task-io-{uuid4().hex}"
    with psycopg.connect(dsn) as setup:
        setup.execute("CREATE TABLE task_io_commit (id integer)")
        setup.execute("""CREATE FUNCTION task_io_delay() RETURNS trigger AS $$
          BEGIN PERFORM pg_sleep(5); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        setup.execute("""CREATE CONSTRAINT TRIGGER task_io_commit_delay AFTER INSERT
          ON task_io_commit DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION task_io_delay()""")
    database = PostgresDatabase(
        make_conninfo(dsn, application_name=label), deployment_namespace="task-io"
    )
    started = time.monotonic()
    connection = database.connect_task_io(timeout_seconds=0.4)
    with pytest.raises(TimeoutError, match="Task storage"):
        with connection:
            connection.execute("INSERT INTO task_io_commit VALUES (1)")
    assert connection.closed and time.monotonic() - started < 0.8
    with psycopg.connect(dsn, autocommit=True) as verify:
        until = time.monotonic() + 1
        while verify.execute(
            "SELECT 1 FROM pg_stat_activity WHERE application_name=%s", (label,)
        ).fetchone():
            assert time.monotonic() < until, "expired Task query kept running in PostgreSQL"
            time.sleep(0.01)
        assert verify.execute("SELECT COUNT(*) FROM task_io_commit").fetchone() == (0,)


def test_lock_timeout_releases_connection_and_preserves_failure(scratch: tuple[str, str]) -> None:
    dsn, _ = scratch
    database = PostgresDatabase(dsn, deployment_namespace="task-io")
    key = uuid4().int % (2**63 - 1)
    with psycopg.connect(dsn) as holder:
        holder.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        connection = database.connect_task_io(timeout_seconds=0.4)
        started = time.monotonic()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with connection:
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        assert connection.closed and time.monotonic() - started < 0.3


@pytest.mark.parametrize("environment_service", [False, True])
def test_service_hostname_is_resolved_before_native_connect(
    scratch: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_service: bool,
) -> None:
    dsn, _ = scratch
    settings = conninfo_to_dict(dsn)
    service = tmp_path / "pg_service.conf"
    service.write_text(f"[task-io]\nhost=localhost\nport={settings['port']}\n")
    monkeypatch.setenv("PGSERVICEFILE", str(service))
    params = {
        key: value for key, value in settings.items() if key not in {"host", "hostaddr", "port"}
    }
    if environment_service:
        monkeypatch.setenv("PGSERVICE", "task-io")
    else:
        params["service"] = "task-io"
    factory = task_io.TaskIoConnections(make_conninfo("", **params))
    attempts = factory._resolve(time.monotonic() + 2)
    resolved = bool(attempts) and all(attempt.get("hostaddr") for attempt in attempts)
    assert resolved, "service hostname escaped the bounded resolver into synchronous libpq DNS"
    assert all(attempt.get("host") == "localhost" for attempt in attempts)
    with factory.connect() as connection:
        assert connection.execute("SELECT 1 AS ready").fetchone() == {"ready": 1}


def test_stalled_dns_child_is_killed_and_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    children: list[subprocess.Popen[str]] = []
    spawn = subprocess.Popen

    def record_child(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        child = cast("subprocess.Popen[str]", spawn(*args, **kwargs))
        children.append(child)
        return child

    monkeypatch.setattr(task_io, "RESOLVE_SCRIPT", "import time; time.sleep(10)")
    monkeypatch.setattr(subprocess, "Popen", record_child)
    database = PostgresDatabase(
        make_conninfo(host="stalled-resolver.invalid", password="do-not-log"),
        deployment_namespace="task-io",
    )
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="DNS deadline"):
        database.connect_task_io(timeout_seconds=0.25)
    assert time.monotonic() - started < 0.7
    assert len(children) == 1 and children[0].poll() is not None
    assert "do-not-log" not in str(children[0].args)


def test_secondary_close_error_does_not_replace_query_timeout(
    scratch: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn, _ = scratch
    close = task_io.TaskIoConnection.close

    def broken_close(self: task_io.TaskIoConnection) -> None:
        close(self)
        raise RuntimeError("secondary cleanup failure")

    monkeypatch.setattr(task_io.TaskIoConnection, "close", broken_close)
    connection = PostgresDatabase(dsn, deployment_namespace="task-io").connect_task_io(
        timeout_seconds=0.25,
    )
    with pytest.raises(TimeoutError, match="Task storage"):
        with connection:
            connection.execute("SELECT pg_sleep(2)")
    assert connection.closed


def test_secondary_generator_close_error_preserves_deadline() -> None:
    from collections.abc import Generator

    def broken_cleanup() -> Generator[int, None, None]:
        try:
            yield 1
        finally:
            raise RuntimeError("secondary generator cleanup")

    budgeted = task_io._budgeted(broken_cleanup(), time.monotonic() + 0.01)
    assert next(budgeted) == 1
    time.sleep(0.02)
    with pytest.raises(TimeoutError, match="Task storage"):
        budgeted.send(None)


def test_connection_loss_is_closed_without_replaying_query(scratch: tuple[str, str]) -> None:
    dsn, _ = scratch
    connection = PostgresDatabase(dsn, deployment_namespace="task-io").connect_task_io()
    pid = connection.info.backend_pid
    with psycopg.connect(dsn, autocommit=True) as killer:
        assert killer.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone() == (True,)
    started = time.monotonic()
    with pytest.raises(psycopg.OperationalError):
        with connection:
            connection.execute("SELECT 1")
    assert connection.closed and time.monotonic() - started < 0.5


def test_confirmed_server_cancel_allows_bounded_savepoint_recovery(
    scratch: tuple[str, str],
) -> None:
    dsn, _ = scratch
    with psycopg.connect(dsn) as setup:
        setup.execute("CREATE TABLE task_io_prefix(id integer)")
    with PostgresDatabase(dsn, deployment_namespace="task-io").connect_task_io() as connection:
        connection.execute("INSERT INTO task_io_prefix VALUES(1)")
        connection.execute("SAVEPOINT slow_header")
        connection.execute("SET LOCAL statement_timeout='50ms'")
        with pytest.raises(psycopg.errors.QueryCanceled):
            connection.execute("SELECT pg_sleep(2)")
        assert not connection.closed
        connection.execute("ROLLBACK TO SAVEPOINT slow_header")
        connection.execute("RELEASE SAVEPOINT slow_header")
        connection.execute("INSERT INTO task_io_prefix VALUES(2)")
    assert connection.closed
    with psycopg.connect(dsn) as verify:
        assert verify.execute("SELECT id FROM task_io_prefix ORDER BY id").fetchall() == [
            (1,),
            (2,),
        ]
