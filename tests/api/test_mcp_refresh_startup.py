"""Refresh startup uses one admitted authority and never discovers at boot."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest
from agent_core.domain.extensions import McpConnection
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from fastapi.testclient import TestClient
from zebra_agent_api import extension_composition, http
from zebra_agent_config import load_settings

from tests.agent_runtime import test_mcp_catalog_discovery as discovery
from tests.agent_runtime.test_mcp_catalog_refresh import setup
from tests.api import test_mcp_credential_composition as fixtures
from tests.api.test_extension_composition import _cloud_composition
from tests.api.test_extension_reads import AUTH, Authorizer

mounted = fixtures.mounted
cloud_startup = fixtures.cloud_startup
dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
network = discovery.network
PATH = "/v1/extensions/mcp-connections/mcp/refresh"


def enabled(settings):
    return replace(
        settings, mcp_credentials=replace(settings.mcp_credentials, refresh_enabled=True)
    )


def test_refresh_default_and_opt_in(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert not load_settings(env={}).mcp_credentials.refresh_enabled
    assert load_settings(
        env={"ZEBRA_CLOUD_MCP_REFRESH_ENABLED": "true"}
    ).mcp_credentials.refresh_enabled


def test_boot_does_not_discover_and_shares_components(cloud_startup, mounted, monkeypatch, network):
    resolver, _ = cloud_startup
    captured = AsyncMock(return_value=http.JSONResponse({"ok": True}))
    monkeypatch.setattr(http, "extension_management_response", captured)
    app = http.create_http_app(settings=enabled(mounted), host_grant_authorizer=Authorizer())
    with TestClient(app) as api:
        assert api.post(PATH, headers=AUTH).status_code == 200
    args = captured.await_args.kwargs
    refresh, credentials = args["refresh"], args["service"]
    assert refresh.connections is credentials.store
    assert refresh.protector is credentials.protector
    assert refresh.catalogs._dsn == resolver.return_value.dsn
    assert refresh.deployment_namespace == resolver.return_value.deployment_namespace
    assert network[0] == []


def test_credentials_only_does_not_enable_refresh(cloud_startup, mounted, monkeypatch, network):
    refresh = Mock(side_effect=AssertionError("must not compose refresh"))
    monkeypatch.setattr(extension_composition, "McpCatalogRefresh", refresh)
    app = http.create_http_app(settings=mounted, host_grant_authorizer=Authorizer())
    with TestClient(app) as api:
        assert api.post(PATH, headers=AUTH).status_code == 404
    refresh.assert_not_called()
    assert network[0] == []


@pytest.mark.parametrize("injected", [False, True])
def test_requires_automatic_credentials(mounted, monkeypatch, injected):
    create = Mock(side_effect=AssertionError("must reject before app creation"))
    monkeypatch.setattr(http, "create_app", create)
    settings = enabled(mounted)
    if not injected:
        settings = replace(
            settings, mcp_credentials=replace(settings.mcp_credentials, enabled=False)
        )
    with pytest.raises(ValueError, match="automatically composed credentials"):
        http.create_http_app(
            settings=settings, mcp_credential_management=Mock() if injected else None
        )
    create.assert_not_called()


@pytest.mark.parametrize("bearer", [False, True])
def test_real_automatic_refresh_and_restart(mounted, network, dsn, bearer):
    _, verified, connection = setup()
    if bearer:
        connection = McpConnection.model_validate(
            connection.model_dump() | {"auth_mode": "bearer", "auth_state": "pending"}
        )
    cloud = replace(_cloud_composition(), dsn=dsn, deployment_namespace="dev")
    configs = PostgresExtensionStore(dsn, deployment_namespace="dev")
    asyncio.run(
        configs.save_mcp(scope=connection.scope, connection=connection, expected_revision=None)
    )

    def application():
        return TestClient(
            http.create_http_app(
                settings=enabled(mounted),
                cloud_composition=cloud,
                host_grant_authorizer=Authorizer(verified),
            )
        )

    with application() as api:
        revision = 1
        if bearer:
            response = api.post(
                PATH.replace("/refresh", "/credentials"),
                headers=AUTH | {"If-Match": '"1"'},
                json={"token": "mounted-fixture-token"},
            )
            assert response.status_code == 200, response.text
            revision = 2
        response = api.post(PATH, headers=AUTH | {"If-Match": f'"{revision}"'})
        assert response.status_code == 200, response.text
    assert all(
        header == ("Bearer mounted-fixture-token" if bearer else None) for _, header in network[0]
    )
    stored = asyncio.run(
        PostgresMcpCatalogStore(dsn, deployment_namespace="dev").latest(
            scope=connection.scope, connection_id="mcp", config_revision=revision
        )
    )
    assert stored.digest == response.json()["catalog_digest"]
    network[1][:] = [{"tools": [discovery.tool()]}]
    with application() as api:
        assert (
            api.post(PATH, headers=AUTH | {"If-Match": f'"{revision}"'}).json() == response.json()
        )
