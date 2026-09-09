import json
import urllib.request

import pytest
from agent_core.domain.extension_snapshots import (
    ExtensionPermissions,
    ExtensionSnapshot,
    McpSnapshotEntry,
)
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_integrations.openai_payloads import internal_tool_names, provider_tool_names
from agent_runtime.cloud_mcp_transport import CloudMcpTransport
from agent_runtime.harness import LocalToolGateway
from agent_runtime.mcp_http_authorization import McpHttpBearerCredential
from agent_runtime.mcp_protocol import McpProtocolError
from agent_security.secret_store import SecretMaterial
from agent_tools import McpProxyRequest, McpToolTarget

from tests.agent_runtime.test_mcp_catalog_discovery import CONNECTION
from tests.agent_runtime.test_mcp_http_streaming import Response
from tests.agent_runtime.test_mcp_stdio import _tool_call


def setup(authorize=lambda *args: None, *, bearer=False):
    connection = CONNECTION.model_copy(update={"enabled": True})
    if bearer:
        connection = type(connection).model_validate(
            connection.model_dump()
            | {"auth_mode": "bearer", "auth_state": "ready", "credential_ref": "secret-ref"}
        )
    catalog = McpToolCatalog(
        connection=connection,
        protocol_version="2025-11-25",
        tools=(
            McpCatalogTool(
                name="events.search",
                description="Search events",
                input_schema_json=json.dumps(
                    {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    }
                ),
            ),
        ),
    )
    entry = McpSnapshotEntry(
        connection=connection,
        catalog_digest=catalog.digest,
        permissions=ExtensionPermissions(tools=("events.search",)),
    )
    snapshot = ExtensionSnapshot(
        scope=connection.scope, session_id="session", turn_id="turn", mcp=(entry,)
    )
    return CloudMcpTransport(snapshot, (catalog,), authorize=authorize), snapshot, catalog


@pytest.fixture
def wire(monkeypatch):
    frames = []

    class Opener:
        def open(self, request, timeout):
            frame = json.loads(request.data)
            frames.append((frame, request.get_header("Authorization")))
            result = (
                {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
                if frame["method"] == "initialize"
                else {"content": [{"type": "text", "text": "matched event"}]}
            )
            return Response({"jsonrpc": "2.0", "id": frame.get("id"), "result": result})

    monkeypatch.setattr("agent_runtime.mcp_http.reject_non_public_resolution", lambda *a, **k: None)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    return frames


def request(transport, arguments=None):
    _, server, tool = transport.model_tools[0].name.split(".")
    return McpProxyRequest("call", McpToolTarget(server, tool), arguments or {"query": "today"})


def test_cloud_aliases_fit_provider_contract_and_round_trip():
    transport, _, _ = setup()
    names = provider_tool_names(transport.model_tools)
    assert len(names[0]) <= 64
    assert (
        internal_tool_names(transport.model_tools, names)[names[0]] == transport.model_tools[0].name
    )


def test_harness_calls_pinned_remote_tool_without_discovery(tmp_path, wire):
    checked = []

    def authorize(entry, operation, endpoint, frame):
        checked.append(frame["method"])
        assert operation.target.tool_name == "events.search"
        assert operation.target.server_name == CONNECTION.connection_id

    transport, _, _ = setup(authorize)
    gateway = LocalToolGateway(tmp_path, cloud_mcp_transport=transport)
    assert wire == []
    try:
        result = gateway.execute(_tool_call(transport.model_tools[0].name, {"query": "today"}))
        assert result.status.value == "executed", result
        assert "matched event" in result.output
        assert "UNTRUSTED MCP OUTPUT" in result.output
        assert checked == ["initialize", "notifications/initialized", "tools/call"]
        assert [frame["method"] for frame, _ in wire] == checked
        assert wire[-1][0]["params"] == {"name": "events.search", "arguments": {"query": "today"}}
    finally:
        gateway.close()


def test_bearer_is_resolved_per_frame(wire):
    def authorize(entry, operation, endpoint, frame):
        return McpHttpBearerCredential(
            endpoint, SecretMaterial("test", "test", value="fixture-token")
        )

    transport, _, _ = setup(authorize, bearer=True)
    result = transport.execute(request(transport))
    assert len(wire) == 3 and all(header == "Bearer fixture-token" for _, header in wire)
    assert "fixture-token" not in repr(result)


def test_revocation_before_tool_frame_prevents_call(wire):
    def authorize(entry, operation, endpoint, frame):
        if frame["method"] == "tools/call":
            raise ValueError("private-backend-detail")

    transport, _, _ = setup(authorize)
    with pytest.raises(McpProtocolError):
        transport.execute(request(transport))
    assert all(frame["method"] != "tools/call" for frame, _ in wire)


def test_bad_arguments_and_unselected_calls_do_not_send(wire):
    transport, _, _ = setup()
    with pytest.raises(McpProtocolError):
        transport.execute(request(transport, {"unknown": "value"}))
    with pytest.raises(McpProtocolError):
        transport.execute(McpProxyRequest("x", McpToolTarget("other", "search")))
    assert wire == []


def test_catalog_binding_and_process_mixing_rejected(tmp_path):
    transport, snapshot, catalog = setup()
    with pytest.raises(ValueError, match="binding mismatch"):
        CloudMcpTransport(
            snapshot,
            (catalog.model_copy(update={"protocol_version": "other"}),),
            authorize=lambda *a: None,
        )
    with pytest.raises(ValueError, match="unavailable"):
        LocalToolGateway(tmp_path, cloud_mcp_transport=transport, mcp_allowlist=("mcp.old.search",))
