import io
import json
import time
import urllib.request
from email.message import Message

import pytest
from agent_core.domain.extension_snapshots import (
    ExtensionPermissions,
    ExtensionSnapshot,
    McpSnapshotEntry,
)
from agent_runtime.cloud_mcp_transport import CloudMcpTransport
from agent_runtime.mcp_catalog_discovery import _DiscoveryServer, discover_mcp_tool_catalog
from agent_runtime.mcp_http_authorization import McpHttpBearerCredential
from agent_runtime.mcp_http_egress import PublicMcpHttpsHandler
from agent_runtime.mcp_protocol import MAX_MCP_FRAME_BYTES, McpProtocolError
from agent_runtime.mcp_sse import McpSseSession, _read_endpoint
from agent_security.secret_store import SecretMaterial

from tests.agent_runtime.test_cloud_mcp_transport import request
from tests.agent_runtime.test_mcp_catalog_discovery import CONNECTION, tool


def event(result, request_id):
    return b"data: " + json.dumps({
        "jsonrpc": "2.0", "id": request_id, "result": result,
    }).encode() + b"\n\n"


class Response(io.BytesIO):
    def __init__(self, body=b""):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = "text/event-stream"


@pytest.fixture
def network(monkeypatch):
    sent, streams = [], []
    result = {"tools": [tool("fetch")]}

    class Opener:
        def open(self, req, timeout):
            sent.append(req)
            if req.method == "GET":
                stream = Response(
                    b"event: endpoint\ndata: /messages?session_id=fixture\n\n"
                    + event({"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}, 1)
                    + event(result, 2)
                )
                streams.append(stream)
                return stream
            return Response()

    def build(*handlers):
        assert any(isinstance(handler, PublicMcpHttpsHandler) for handler in handlers)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    return sent, streams, result


def test_discovery_then_cloud_call_uses_sse_and_live_guards(network):
    sent, streams, result = network
    connection = CONNECTION.model_copy(update={"transport": "sse", "enabled": True})
    checked = []
    catalog = discover_mcp_tool_catalog(
        connection, frame_authorizer=lambda endpoint, frame: checked.append(frame["method"]),
    )
    assert catalog.protocol_version == "2024-11-05"
    assert [item.name for item in catalog.tools] == ["fetch"]
    assert [req.method for req in sent] == ["GET", "POST", "POST", "POST"]
    assert checked == ["initialize", "initialize", "notifications/initialized", "tools/list"]
    assert all(stream.closed for stream in streams)
    result.clear()
    result.update({"content": [{"type": "text", "text": "Example Domain"}], "isError": False})
    entry = McpSnapshotEntry(
        connection=connection, catalog_digest=catalog.digest,
        permissions=ExtensionPermissions(tools=("fetch",)),
    )
    snapshot = ExtensionSnapshot(
        scope=connection.scope, session_id="session", turn_id="turn", mcp=(entry,),
    )
    transport = CloudMcpTransport(
        snapshot, (catalog,),
        authorize=lambda entry, operation, endpoint, frame: checked.append(frame["method"]),
    )
    response = transport.execute(request(transport))
    assert "Example Domain" in response.output
    assert response.metadata == {"transport": "sse", "mcp_is_error": False}
    assert checked[-4:] == ["initialize", "initialize", "notifications/initialized", "tools/call"]
    assert all(stream.closed for stream in streams)


@pytest.mark.parametrize("endpoint", [
    "https://other.example/messages", "http://mcp.example/messages",
    "//127.0.0.1/messages", " /messages", "/messages\t", "/messages#fragment",
])
def test_invalid_derived_endpoint_rejected(endpoint):
    stream = io.BytesIO(f"event: endpoint\ndata: {endpoint}\n\n".encode())
    with pytest.raises(ValueError):
        _read_endpoint(stream, "https://mcp.example/sse", time.monotonic() + 2)


@pytest.mark.parametrize("body", [b"", b":" + b"x" * MAX_MCP_FRAME_BYTES])
def test_endpoint_stream_is_bounded(body):
    with pytest.raises(McpProtocolError):
        _read_endpoint(io.BytesIO(body), "https://mcp.example/sse", time.monotonic() + 2)


def test_denied_authority_sends_nothing(network):
    sent, _, _ = network

    def deny(*args):
        raise ValueError("private authority detail")

    with pytest.raises(McpProtocolError, match="authorization failed"):
        with McpSseSession(_DiscoveryServer(CONNECTION.endpoint), 2, frame_authorizer=deny):
            pass
    assert sent == []


def test_revocation_before_call_closes_stream(network):
    sent, streams, _ = network

    def guard(endpoint, frame):
        if frame["method"] == "tools/list":
            raise ValueError("revoked")

    with pytest.raises(McpProtocolError, match="authorization failed"):
        with McpSseSession(_DiscoveryServer(CONNECTION.endpoint), 2, frame_authorizer=guard) as s:
            s.request("tools/list", {})
    assert len(sent) == 3
    assert all(stream.closed for stream in streams)


def test_bearer_is_bound_to_original_endpoint_and_resolved_per_frame(network):
    sent, streams, _ = network
    resolved = []

    def credential(endpoint, frame):
        assert endpoint == CONNECTION.endpoint
        resolved.append(frame["method"])
        return McpHttpBearerCredential(
            endpoint, SecretMaterial("test", "test", value="fixture-token"),
        )

    with McpSseSession(
        _DiscoveryServer(CONNECTION.endpoint), 2, credential_resolver=credential,
    ) as session:
        session.request("tools/list", {})
    assert len(resolved) == 4
    assert all(req.get_header("Authorization") == "Bearer fixture-token" for req in sent)
    assert all(stream.closed for stream in streams)


def test_sse_contract_roundtrip_and_stdio_still_rejected():
    from agent_core.application.mcp_connections import McpConnectionCreate

    connection = type(CONNECTION).model_validate(CONNECTION.model_dump() | {"transport": "sse"})
    assert type(connection).model_validate_json(connection.model_dump_json()) == connection
    assert McpConnectionCreate(endpoint=CONNECTION.endpoint, transport="sse").transport == "sse"
    with pytest.raises(ValueError):
        McpConnectionCreate(endpoint=CONNECTION.endpoint, transport="stdio")
