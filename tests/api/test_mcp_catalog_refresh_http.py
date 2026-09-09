"""Protected HTTP refresh through actual service composition."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.extensions import McpConnection
from agent_core.domain.mcp_credentials import McpCredentialProtectionError
from agent_core.ports.extensions import ExtensionStore
from agent_core.ports.mcp_catalog import McpCatalogIntegrityError
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_storage import sqlite_control_plane_stores
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from agent_storage.postgres.mcp_credentials import PostgresMcpCredentialStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app

from tests.agent_runtime import test_mcp_catalog_discovery as discovery
from tests.agent_runtime.test_mcp_catalog_refresh import grant, setup
from tests.agent_storage import test_postgres_mcp_credentials as fixtures
from tests.api.test_extension_reads import AUTH, Authorizer
from tests.api.test_host_auth_http import _cloud_settings

network = discovery.network
dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
protector = fixtures.protector
PATH = "/v1/extensions/mcp-connections/mcp/refresh"
HEADERS = AUTH | {"If-Match": '"1"'}


def client(tmp_path, service, verified=None, enabled=True):
    database = tmp_path / "refresh.sqlite"
    return TestClient(
        create_http_app(
            database,
            settings=replace(
                _cloud_settings("postgresql://unused/zebra"),
                cloud_extensions_manage_enabled=enabled,
            ),
            stores=sqlite_control_plane_stores(database),
            extension_store=AsyncMock(spec=ExtensionStore),
            mcp_catalog_refresh=service,
            host_grant_authorizer=Authorizer(verified or grant()),
        )
    )


def test_protected_refresh_http(tmp_path, network):
    service, verified, _ = setup()
    response = client(tmp_path, service, verified).post(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["tool_count"] == 1
    assert set(response.json()) == {
        "connection_id",
        "config_revision",
        "catalog_digest",
        "tool_count",
    }
    assert response.headers["etag"] == '"1"' and response.headers["cache-control"] == "no-store"


def test_boundary_rejections(tmp_path, network):
    service, verified, _ = setup()
    api = client(tmp_path, service, verified)
    assert api.post(PATH).status_code == 401
    assert api.post(PATH, headers=AUTH).status_code == 428
    assert (
        api.post(PATH, headers=HEADERS, json={"endpoint": "https://other.test"}).status_code == 422
    )
    assert api.post(PATH + "?x=y", headers=HEADERS).status_code == 422
    assert api.post(PATH, headers=AUTH | {"If-Match": 'W/"1"'}).status_code == 422
    assert api.get(PATH, headers=AUTH).status_code == 405
    assert (
        client(tmp_path, service, grant(["extensions.read"]))
        .post(PATH, headers=HEADERS)
        .status_code
        == 403
    )
    assert client(tmp_path, service, enabled=False).post(PATH, headers=HEADERS).status_code == 404
    assert client(tmp_path, None).post(PATH, headers=HEADERS).status_code == 404
    assert network[0] == [] and service.catalogs.mock_calls == []


@pytest.mark.parametrize(
    "failure", [McpCredentialProtectionError, McpCatalogIntegrityError, OSError]
)
def test_backend_errors_are_scrubbed(tmp_path, failure):
    service = AsyncMock(spec=McpCatalogRefresh)
    service.refresh.side_effect = failure("private-token-diagnostic")
    response = client(tmp_path, service).post(PATH, headers=HEADERS)
    assert response.status_code == 503
    assert "private-token" not in response.text


@pytest.mark.parametrize("bearer", [False, True])
def test_real_http_refresh_persists(tmp_path, network, dsn, protector, bearer):
    _, verified, connection = setup()
    if bearer:
        connection = McpConnection.model_validate(
            connection.model_dump()
            | {"auth_mode": "bearer", "auth_state": "ready", "credential_ref": "credential"}
        )
    configs = PostgresExtensionStore(dsn, deployment_namespace="dev")
    asyncio.run(
        configs.save_mcp(scope=connection.scope, connection=connection, expected_revision=None)
    )
    catalog_store = PostgresMcpCatalogStore(dsn, deployment_namespace="dev")
    if bearer:
        credentials = PostgresMcpCredentialStore(dsn, deployment_namespace="dev")
        asyncio.run(
            credentials.save(
                scope=connection.scope,
                record=fixtures.record(
                    protector, scope=connection.scope, endpoint=connection.endpoint
                ),
                expected_revision=None,
            )
        )
    service = McpCatalogRefresh(
        PostgresMcpCredentialStore(dsn, deployment_namespace="dev"), catalog_store, protector, "dev"
    )
    response = client(tmp_path, service, verified).post(PATH, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert all(
        header == (f"Bearer {fixtures.TOKEN}" if bearer else None) for _, header in network[0]
    )
    assert fixtures.TOKEN not in response.text
    assert (
        asyncio.run(
            catalog_store.latest(scope=connection.scope, connection_id="mcp", config_revision=1)
        ).digest
        == response.json()["catalog_digest"]
    )
    assert (
        client(tmp_path, service, grant())
        .post(PATH, headers=AUTH | {"If-Match": '"2"'})
        .status_code
        == 409
    )
