"""No-framework native checks; run with ZEBRA_TEST_POSTGRES_DSN on a scratch PG."""

import os
from datetime import UTC, datetime
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
from agent_storage.postgres.connection_scope import (
    current_connection_scope,
    postgres_connection_scope,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_io import TaskIoConnection, task_io_deadline
from psycopg import pq
from psycopg.conninfo import make_conninfo
from zebra_agent_worker.execution_recovery import execute_claimed_with_stale_retry


def check(dsn: str) -> None:
    assert pq.version() >= 170000, "native bounded reuse check requires libpq17+"
    database = PostgresDatabase(dsn, deployment_namespace="run-bounded-check")
    with postgres_connection_scope(task_io=True):
        owner = current_connection_scope()
        with task_io_deadline(monotonic() + 0.25), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as first:
                raw, old_deadline = first.connection, first.deadline
                first.execute("SET TRANSACTION READ ONLY")
                pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        assert not raw.closed
        with database.connect() as ordinary:
            assert ordinary.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] != pid
            assert getattr(ordinary, "connection", None) is not raw
        sleep(max(0, old_deadline - monotonic()) + 0.02)
        with task_io_deadline(monotonic() + 0.5), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as second:
                assert second.connection is raw and second.deadline > old_deadline
                assert second.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"] == pid
                assert second.execute("SHOW transaction_read_only").fetchone()[
                    "transaction_read_only"
                ] == "off"
            # Ordinary coverage scopes still own their separate callback lifetime.
            with postgres_connection_scope():
                assert current_connection_scope() is not owner
            assert current_connection_scope() is owner
        # An explicit next Run is a separate owner, even if nested accidentally.
        with postgres_connection_scope(task_io=True):
            with task_io_deadline(monotonic() + 0.5), postgres_connection_scope(bounded=True):
                with database.connect_task_io() as other:
                    assert other.connection is not raw
        assert not raw.closed
    assert raw.closed

    # The database can close an idle backend while the Agent waits on the model.
    with postgres_connection_scope(task_io=True):
        with task_io_deadline(monotonic() + 0.5), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as first:
                dead = first.connection
                pid = first.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        with psycopg.connect(dsn, autocommit=True) as peer:
            assert peer.execute("SELECT pg_terminate_backend(%s,1000)", (pid,)).fetchone()[0]
        sleep(0.05)
        with task_io_deadline(monotonic() + 0.5), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as second:
                assert second.connection is not dead and dead.closed
                assert second.execute("SELECT 42 AS value").fetchone()["value"] == 42

    # A shorter callback budget still cancels and discards the reused socket.
    with postgres_connection_scope(task_io=True):
        with task_io_deadline(monotonic() + 0.5), postgres_connection_scope(bounded=True):
            with database.connect_task_io() as first:
                cancelled = first.connection
                first.execute("SELECT 1")
        deadline = monotonic() + 0.1
        try:
            with task_io_deadline(deadline), postgres_connection_scope(bounded=True):
                with database.connect_task_io() as second:
                    assert second.connection is cancelled
                    second.execute("SELECT pg_sleep(1)")
        except TimeoutError:
            pass
        else:
            raise AssertionError("reused connection escaped the shorter callback deadline")
        assert cancelled.closed and monotonic() < deadline + 0.4

    # Unknown COMMIT is propagated once and never automatically replayed.
    commit = TaskIoConnection.commit
    calls = []

    def unknown(connection):
        calls.append(connection)
        commit(connection)
        connection.close()
        raise TimeoutError("unknown COMMIT acknowledgement")

    with postgres_connection_scope(task_io=True):
        with patch.object(TaskIoConnection, "commit", unknown):
            try:
                with task_io_deadline(monotonic() + 0.5), postgres_connection_scope(bounded=True):
                    with database.connect_task_io() as connection:
                        connection.execute("SELECT 1")
            except TimeoutError as error:
                assert str(error) == "unknown COMMIT acknowledgement"
            else:
                raise AssertionError("unknown COMMIT was swallowed")
        assert len(calls) == 1 and calls[0].closed
    # Complete DSN keys isolate sessions and the owner retains at most eight idle sockets.
    with postgres_connection_scope(task_io=True):
        raw_connections = []
        for index in range(9):
            other = PostgresDatabase(
                make_conninfo(dsn, application_name=f"bounded-key-{index}"),
                deployment_namespace="run-bounded-check",
            )
            with task_io_deadline(monotonic() + 0.5), postgres_connection_scope(bounded=True):
                with other.connect_task_io() as connection:
                    raw_connections.append(connection.connection)
                    connection.execute("SELECT 1")
        assert len(current_connection_scope().connections) == 8
        assert raw_connections[-1].closed
    assert all(connection.closed for connection in raw_connections)

    for cloud in (False, True):
        for fail in (False, True):
            owners = []

            def execute_once(*_args, _owners=owners, _cloud=cloud, _fail=fail, **_kwargs):
                owner = current_connection_scope()
                _owners.append(owner)
                assert (owner is not None) is _cloud
                if _cloud:
                    assert owner.task_io_only
                if _fail:
                    raise ValueError("primary execution refusal")
                return "completed"

            service = SimpleNamespace(
                _execution_namespace="cloud" if cloud else None,
                _execute_claimed_session_once=execute_once,
            )
            try:
                result = execute_claimed_with_stale_retry(
                    service, SimpleNamespace(lease=SimpleNamespace(session_id=uuid4())),
                    started_at=datetime.now(UTC), ownership_check=lambda: None,
                )
            except ValueError as error:
                assert fail and str(error) == "primary execution refusal"
            else:
                assert not fail and result == "completed"
            assert len(owners) == 1 and (not cloud or owners[0].closed)
    print("Run ownership/budgets/reset/cleanup/unknown COMMIT and cloud-only entry wiring pass")


if __name__ == "__main__":
    check(os.environ["ZEBRA_TEST_POSTGRES_DSN"])
