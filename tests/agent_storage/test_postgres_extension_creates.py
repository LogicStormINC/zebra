"""Idempotent creation acceptance exclusively inside disposable PostgreSQL schemas."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.application.mcp_connections import create_mcp_connection
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_storage import sqlite_control_plane_stores
from agent_storage.postgres.extensions import PostgresExtensionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app

from tests.agent_core.test_mcp_connections import PAYLOAD
from tests.agent_security.test_extension_authority import _verified
from tests.agent_storage import test_postgres_extensions as fixtures
from tests.api.test_extension_creates import HEADERS, PATH
from tests.api.test_extension_reads import AUTH, Authorizer
from tests.api.test_host_auth_http import _cloud_settings

SCOPE = fixtures.SCOPE
dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn


def test_concurrent_restart_replay_after_toggle(dsn: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
    fresh = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        results = await asyncio.gather(*(
            create_mcp_connection(store=adapter, scope=SCOPE, idempotency_key="same",
                                  payload=PAYLOAD)
            for adapter in (store, fresh, store, fresh)
        ))
        assert sum(created for _, created in results) == 1
        original = results[0][0]
        assert all(record == original for record, _ in results)
        current = await set_extension_enabled(
            store=store, scope=SCOPE, kind="mcp", object_id=original.connection_id,
            expected_revision=1, enabled=True,
        )
        replay, created = await create_mcp_connection(
            store=fresh, scope=SCOPE, idempotency_key="same", payload=PAYLOAD,
        )
        assert not created and replay == current
        assert await fresh.get_mcp_creation(
            scope=SCOPE, connection_id=original.connection_id,
        ) == original
        with pytest.raises(ExtensionRevisionConflictError):
            await create_mcp_connection(store=fresh, scope=SCOPE, idempotency_key="same",
                                        payload=PAYLOAD | {"auth_mode": "bearer"})
        with store.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS count FROM extension_configuration_revisions"
            ).fetchone() == {"count": 2}

    asyncio.run(check())


@pytest.mark.parametrize("coordinate", [
    "authority_issuer", "namespace_id", "principal_id", "workspace_id", "deployment",
])
def test_creation_scope_isolation(dsn: str, coordinate: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
    other = PostgresExtensionStore(
        dsn, deployment_namespace="cloud-b" if coordinate == "deployment" else "cloud-a",
    )
    scope = SCOPE if coordinate == "deployment" else SCOPE.model_copy(update={coordinate: "other"})

    async def check() -> None:
        original, _ = await create_mcp_connection(
            store=store, scope=SCOPE, idempotency_key="key", payload=PAYLOAD,
        )
        with pytest.raises(ExtensionNotFoundError):
            await other.get_mcp_creation(scope=scope, connection_id=original.connection_id)
        separate, created = await create_mcp_connection(
            store=other, scope=scope, idempotency_key="key",
            payload=PAYLOAD | {"auth_mode": "oauth"},
        )
        assert created and separate.auth_state == "pending"
        assert separate.connection_id == original.connection_id
        assert await store.get_mcp_creation(
            scope=SCOPE, connection_id=original.connection_id,
        ) == original

    asyncio.run(check())


def test_postgres_http_create_get_patch_replay(dsn: str, tmp_path: Path) -> None:
    database = tmp_path / "http.sqlite"
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
    client = TestClient(create_http_app(
        database,
        settings=replace(_cloud_settings(dsn), cloud_extensions_manage_enabled=True),
        stores=sqlite_control_plane_stores(database), extension_store=store,
        host_grant_authorizer=Authorizer(_verified(
            scopes=["extensions.read", "extensions.manage"],
        )),
    ))
    response = client.post(PATH, headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 201
    location = response.headers["location"]
    original = client.get(location, headers=AUTH)
    assert original.status_code == 200 and original.json() == response.json()
    updated = client.patch(location, headers=AUTH | {"If-Match": '"1"'},
                           json={"enabled": True})
    assert updated.status_code == 200 and updated.headers["etag"] == '"2"'
    replay = client.post(PATH, headers=HEADERS, json=PAYLOAD)
    assert replay.status_code == 200 and replay.json() == updated.json()
    assert replay.headers["etag"] == '"2"'
