"""Native authorization reads are bounded and fail closed on scratch PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import psycopg
import pytest
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres.task_io import TaskIoConnection
from zebra_agent_api.ag_ui_task_view import authorized_task_preflight
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import task_access_response

from tests.api.ag_ui_checkpoint_postgres_support import PgGetReplay
from tests.api.ag_ui_checkpoint_postgres_support import pg_get_replay as _pg_get_replay

pg_get_replay = _pg_get_replay
pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEBRA_HEADER_SCRATCH_DSN"),
    reason="native authorization gate requires the explicit isolated scratch DSN",
)


def test_native_auth_and_preflight_share_one_grant_deadline(
    pg_get_replay: PgGetReplay,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, connections = pg_get_replay, []
    app = _app(fixture)
    connect = PostgresDatabase.connect_task_io

    def bounded(database: PostgresDatabase, **kwargs: Any) -> psycopg.Connection[Any]:
        connection = connect(database, **kwargs)
        assert isinstance(connection, TaskIoConnection)
        connections.append(connection)
        return connection

    def prepare() -> None:
        with PostgresDatabase(fixture.dsn, deployment_namespace="probe").connect_task_io() as read:
            read.execute("SELECT pg_sleep(2)")
        raise AssertionError("expired native query prepared SSE")

    monkeypatch.setattr(PostgresDatabase, "connect_task_io", bounded)
    started = time.monotonic()
    response = asyncio.run(
        authorized_task_preflight(
            lambda: task_access_response(app, str(fixture.session), fixture.verified.context),
            prepare,
            authorization_expires_at=datetime.now(UTC) + timedelta(milliseconds=300),
        )
    )
    assert isinstance(response, ApiResponse) and response.status_code in {403, 503}
    assert time.monotonic() - started < 0.8
    assert len(connections) == 3 and len({read.deadline for read in connections}) == 1
    assert all(read.closed for read in connections)


def _app(fixture: PgGetReplay) -> SimpleNamespace:
    return SimpleNamespace(
        stores=fixture.stores(),
        cloud_control=PostgresDirectControl(
            fixture.dsn, deployment_namespace=fixture.cloud.deployment_namespace
        ),
    )


def test_native_authorization_has_no_unbounded_database_connection(
    pg_get_replay: PgGetReplay,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, connections = pg_get_replay, []
    app = _app(fixture)
    connect = PostgresDatabase.connect_task_io

    def bounded(database: PostgresDatabase, **kwargs: Any) -> psycopg.Connection[Any]:
        connection = connect(database, **kwargs)
        assert isinstance(connection, TaskIoConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(PostgresDatabase, "connect_task_io", bounded)
    with patch.object(PostgresDatabase, "connect", side_effect=AssertionError("unbounded read")):
        assert task_access_response(app, str(fixture.session), fixture.verified.context) is None
    assert len(connections) == 2 and all(connection.closed for connection in connections)


@pytest.mark.parametrize(
    "table,status",
    [
        ("session_projections", "tenant_binding_unavailable"),
        ("task_binding_snapshots", "principal_binding_unavailable"),
    ],
)
def test_native_authorization_lock_returns_unavailable_without_writes(
    pg_get_replay: PgGetReplay,
    table: str,
    status: str,
) -> None:
    fixture = pg_get_replay
    app = _app(fixture)
    with psycopg.connect(fixture.dsn) as holder:
        holder.execute(
            psycopg.sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                psycopg.sql.Identifier(table)
            )
        )
        started = time.monotonic()
        response = task_access_response(app, str(fixture.session), fixture.verified.context)
        assert response is not None and response.status_code == 503
        assert response.body == {"status": status}
        assert time.monotonic() - started < 1
    assert task_access_response(app, str(fixture.session), fixture.verified.context) is None
