"""Exercise actual HTTP JSON-RPC framing with a captured network boundary."""

import asyncio
import json
import urllib.request
from unittest.mock import Mock

import pytest
from agent_core.domain.extensions import McpConnection
from agent_runtime.mcp_catalog_discovery import discover_mcp_tool_catalog
from agent_runtime.mcp_protocol import McpProtocolError
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore

from tests.agent_runtime.test_mcp_http_authorization import credential
from tests.agent_runtime.test_mcp_http_streaming import Response
from tests.agent_storage import test_postgres_extensions as fixtures

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
CONNECTION = McpConnection(
    scope=fixtures.SCOPE, connection_id="mcp", revision=1, endpoint="https://example.test/mcp"
)


def tool(name="search"):
    return {
        "name": name,
        "description": "Find content",
        "inputSchema": {"type": "object", "properties": {}},
    }


@pytest.fixture
def network(monkeypatch):
    sent = []
    pages = [{"tools": [tool()]}]
    config = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}

    class Opener:
        def open(self, request, timeout):
            frame = json.loads(request.data)
            sent.append((frame, request.get_header("Authorization")))
            result = config if frame["method"] == "initialize" else {}
            if frame["method"] == "tools/list":
                result = pages.pop(0)
            return Response({"jsonrpc": "2.0", "id": frame.get("id"), "result": result})

    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution", lambda *a, **kw: None
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    return sent, pages, config


def test_pages_become_complete_bound_catalog(network):
    sent, pages, _ = network
    pages[:] = [{"tools": [tool("second")], "nextCursor": "p2"}, {"tools": [tool("first")]}]
    catalog = discover_mcp_tool_catalog(CONNECTION)
    assert catalog.connection == CONNECTION
    assert catalog.protocol_version == "2025-11-25"
    assert [item.name for item in catalog.tools] == ["first", "second"]
    assert [frame["method"] for frame, _ in sent] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/list",
    ]
    assert sent[-1][0]["params"] == {"cursor": "p2"}
    assert all(header is None for _, header in sent)


def test_authenticated_pages_resolve_each_frame(network):
    sent, _, _ = network
    connection = McpConnection.model_validate(
        CONNECTION.model_dump()
        | {"auth_mode": "bearer", "auth_state": "ready", "credential_ref": "ref"}
    )
    count = 0

    def resolve(endpoint, frame):
        nonlocal count
        count += 1
        assert endpoint == connection.endpoint
        return credential(endpoint, f"private-token-{count}")

    catalog = discover_mcp_tool_catalog(connection, credential_resolver=resolve)
    assert [header for _, header in sent] == [f"Bearer private-token-{i}" for i in range(1, 4)]
    assert "private-token" not in catalog.model_dump_json()


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_denial_stops_discovery_without_retry(network, stage):
    sent, pages, _ = network
    pages[:] = [{"tools": [tool()], "nextCursor": "p2"}, {"tools": [tool("other")]}]
    connection = McpConnection.model_validate(
        CONNECTION.model_dump()
        | {"auth_mode": "bearer", "auth_state": "ready", "credential_ref": "ref"}
    )
    calls = 0

    def resolve(endpoint, frame):
        nonlocal calls
        calls += 1
        if calls == stage:
            raise ValueError("private-token")
        return credential(endpoint)

    with pytest.raises(McpProtocolError, match="authorization failed") as error:
        discover_mcp_tool_catalog(connection, credential_resolver=resolve)
    assert "private-token" not in str(error.value)
    assert len(sent) == stage - 1 and calls == stage


@pytest.mark.parametrize("mode", ["bearer", "api_key", "oauth"])
def test_unsupported_or_missing_credentials_do_not_send(network, mode):
    connection = McpConnection.model_validate(
        CONNECTION.model_dump()
        | {"auth_mode": mode, "auth_state": "ready", "credential_ref": "ref"}
    )
    with pytest.raises(McpProtocolError, match="authentication is unavailable"):
        discover_mcp_tool_catalog(connection)
    assert network[0] == []


def test_no_accidental_credentials_for_public_connection(network):
    resolver = Mock()
    with pytest.raises(McpProtocolError, match="cannot receive"):
        discover_mcp_tool_catalog(CONNECTION, credential_resolver=resolver)
    resolver.assert_not_called()
    assert network[0] == []


@pytest.mark.parametrize("bad", ["duplicate", "loop", "invalid", "overflow"])
def test_partial_or_invalid_catalog_is_not_returned(network, bad):
    _, pages, _ = network
    pages[:] = [{"tools": [tool()], "nextCursor": "p2"}]
    pages.append(
        {"tools": [tool()]}
        if bad == "duplicate"
        else {"tools": [], "nextCursor": "p2"}
        if bad == "loop"
        else {"tools": [{"name": "bad", "inputSchema": {"type": "array"}}]}
        if bad == "invalid"
        else {"tools": [tool(f"t{i}") for i in range(16)]}
    )
    with pytest.raises(McpProtocolError):
        discover_mcp_tool_catalog(CONNECTION)


def test_no_tools_capability(network):
    network[2]["capabilities"] = {}
    assert discover_mcp_tool_catalog(CONNECTION).tools == ()
    assert len(network[0]) == 2


def test_discovery_to_real_store_and_failed_refresh(network, dsn):
    configs = PostgresExtensionStore(dsn, deployment_namespace="dev")
    asyncio.run(
        configs.save_mcp(scope=CONNECTION.scope, connection=CONNECTION, expected_revision=None)
    )
    store = PostgresMcpCatalogStore(dsn, deployment_namespace="dev")
    catalog = discover_mcp_tool_catalog(CONNECTION)
    asyncio.run(store.publish(scope=CONNECTION.scope, catalog=catalog))
    network[1][:] = [{"tools": [tool(), tool()]}]
    with pytest.raises(McpProtocolError):
        discover_mcp_tool_catalog(CONNECTION)
    restarted = PostgresMcpCatalogStore(dsn, deployment_namespace="dev")
    assert (
        asyncio.run(
            restarted.latest(scope=CONNECTION.scope, connection_id="mcp", config_revision=1)
        )
        == catalog
    )
