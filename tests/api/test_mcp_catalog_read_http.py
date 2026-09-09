"""Scoped catalog inspection does not discover tools or release credentials."""

import asyncio

from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.extensions import ExtensionNotFoundError
from agent_runtime.mcp_catalog_refresh import McpCatalogRefresh
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from agent_storage.postgres.mcp_credentials import PostgresMcpCredentialStore

from tests.agent_runtime import test_mcp_catalog_discovery as discovery
from tests.agent_runtime.test_mcp_catalog_refresh import grant, setup
from tests.agent_storage import test_postgres_mcp_credentials as fixtures
from tests.api.test_extension_reads import AUTH
from tests.api.test_mcp_catalog_refresh_http import client

PATH = "/v1/extensions/mcp-connections/mcp/catalog"
network = discovery.network
dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
protector = fixtures.protector


def prepared():
    service, _, connection = setup()
    service.catalogs.latest.return_value = McpToolCatalog(
        connection=connection,
        protocol_version="2025-11-25",
        tools=(McpCatalogTool(name="search", input_schema_json='{"type":"object"}'),),
    )
    return service, connection


def test_catalog_read_uses_current_scope_without_network_or_secret_release(tmp_path):
    service, connection = prepared()
    api = client(tmp_path, service, grant(["extensions.read"]))
    response = api.get(PATH, headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["tools"] == [
        {"name": "search", "description": "", "input_schema": {"type": "object"}}
    ]
    assert set(response.json()) == {
        "connection_id",
        "config_revision",
        "catalog_digest",
        "tool_count",
        "tools",
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["etag"] == '"1"'
    service.catalogs.latest.assert_awaited_once_with(
        scope=connection.scope, connection_id="mcp", config_revision=1
    )
    service.connections.get_for_use.assert_not_awaited()
    service.catalogs.publish.assert_not_awaited()


def test_catalog_boundary_rejections(tmp_path):
    service, _ = prepared()
    api = client(tmp_path, service, grant(["extensions.read"]))
    assert api.get(PATH).status_code == 401
    assert api.post(PATH, headers=AUTH).status_code == 405
    assert api.get(PATH + "?scope=other", headers=AUTH).status_code == 422
    assert api.get(PATH, headers=AUTH | {"If-Match": '"1"'}).status_code == 422
    assert (
        client(tmp_path, service, grant(["agent.run"])).get(PATH, headers=AUTH).status_code == 403
    )
    assert client(tmp_path, None).get(PATH, headers=AUTH).status_code == 404
    assert client(tmp_path, service, enabled=False).get(PATH, headers=AUTH).status_code == 404
    service.catalogs.latest.assert_not_awaited()


def test_catalog_missing_current_revision_does_not_fall_back(tmp_path):
    service, _ = prepared()
    service.catalogs.latest.side_effect = ExtensionNotFoundError("private-diagnostic")
    response = client(tmp_path, service, grant(["extensions.read"])).get(PATH, headers=AUTH)
    assert response.status_code == 404 and "private-diagnostic" not in response.text
    assert service.catalogs.latest.await_count == 1


def test_catalog_wrong_scope_is_not_disclosed(tmp_path):
    service, connection = prepared()
    service.connections.get_connection.return_value = connection.model_copy(
        update={"scope": connection.scope.model_copy(update={"principal_id": "other"})}
    )
    response = client(tmp_path, service, grant(["extensions.read"])).get(PATH, headers=AUTH)
    assert response.status_code == 404
    service.catalogs.latest.assert_not_awaited()


def test_catalog_changed_during_read_is_rejected(tmp_path):
    service, connection = prepared()
    service.connections.get_connection.side_effect = [
        connection,
        connection.model_copy(update={"revision": 2}),
    ]
    response = client(tmp_path, service, grant(["extensions.read"])).get(PATH, headers=AUTH)
    assert response.status_code == 409


def test_catalog_mismatched_metadata_is_scrubbed(tmp_path):
    service, connection = prepared()
    service.catalogs.latest.return_value = service.catalogs.latest.return_value.model_copy(
        update={"connection": connection.model_copy(update={"revision": 2})}
    )
    response = client(tmp_path, service, grant(["extensions.read"])).get(PATH, headers=AUTH)
    assert response.status_code == 503
    assert "search" not in response.text


def test_real_refresh_then_read_after_restart(tmp_path, dsn, network, protector):
    _, _, connection = setup()
    configs = PostgresExtensionStore(dsn, deployment_namespace="dev")
    asyncio.run(
        configs.save_mcp(scope=connection.scope, connection=connection, expected_revision=None)
    )

    def service():
        return McpCatalogRefresh(
            PostgresMcpCredentialStore(dsn, deployment_namespace="dev"),
            PostgresMcpCatalogStore(dsn, deployment_namespace="dev"),
            protector,
            "dev",
        )

    refreshed = client(tmp_path, service()).post(
        PATH.replace("/catalog", "/refresh"), headers=AUTH | {"If-Match": '"1"'}
    )
    assert refreshed.status_code == 200
    frames = len(network[0])
    api = client(tmp_path, service(), grant(["extensions.read"]))
    response = api.get(PATH, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["catalog_digest"] == refreshed.json()["catalog_digest"]
    assert response.json()["tools"][0]["name"] == "search"
    assert len(network[0]) == frames
    asyncio.run(
        configs.save_mcp(
            scope=connection.scope,
            connection=connection.model_copy(update={"revision": 2}),
            expected_revision=1,
        )
    )
    assert api.get(PATH, headers=AUTH).status_code == 404
