from __future__ import annotations

import urllib.request
from dataclasses import dataclass

import pytest
from agent_runtime.mcp_http import (
    McpHttpSession,
    StreamableHttpMcpTransport,
    _parse_response_message,
)
from agent_runtime.mcp_protocol import McpProtocolError
from agent_tools import McpProxyRequest, parse_mcp_tool_name


@dataclass(frozen=True)
class _HttpServer:
    name: str
    url: str
    bearer_token_env: str | None = None


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self.headers = {"Content-Type": content_type}
        self._body = body

    def read(self, _n: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


class _FakeOpener:
    def __init__(self, responses: list[tuple[bytes, str]]) -> None:
        self._responses = list(responses)
        self.last_request: urllib.request.Request | None = None

    def open(
        self,
        request: urllib.request.Request,
        timeout: float | None = None,
    ) -> _FakeResponse:
        self.last_request = request
        body, content_type = self._responses.pop(0)
        return _FakeResponse(body, content_type)


def _rpc(
    result: object,
    request_id: int = 1,
    content_type: str = "application/json",
) -> tuple[bytes, str]:
    import json

    payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
    return payload.encode(), content_type


def test_http_session_rejects_non_https_url() -> None:
    session = McpHttpSession(_HttpServer("fixture", "http://example.test/mcp"), 5.0)
    with pytest.raises(McpProtocolError, match="https"):
        session.__enter__()


def test_http_session_rejects_private_network_url() -> None:
    session = McpHttpSession(_HttpServer("fixture", "https://127.0.0.1:9/mcp"), 5.0)
    with pytest.raises(McpProtocolError, match="blocked address"):
        session.__enter__()


def test_parse_response_message_accepts_json_and_event_stream() -> None:
    json_message = _rpc({"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}})
    assert _parse_response_message("fixture", "application/json", json_message[0].decode())[
        "jsonrpc"
    ] == "2.0"

    sse_payload = _rpc({"tools": []}, content_type="text/event-stream")[0].decode()
    sse_text = "event: message\ndata: " + sse_payload + "\n\n"
    parsed = _parse_response_message("fixture", "text/event-stream", sse_text)
    assert parsed["result"] == {"tools": []}


def test_http_transport_discovers_and_executes_over_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bypass the public-address SSRF preflight for the fake https host.
    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution",
        lambda *_args, **_kwargs: None,
    )
    initialize = _rpc(
        {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}},
        request_id=1,
    )
    tools_list = _rpc(
        {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo one value.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                }
            ]
        },
        request_id=2,
    )
    # execute() opens a fresh session that re-initializes before tools/call.
    tool_call = _rpc(
        {"content": [{"type": "text", "text": "echo:zebra"}]},
        request_id=2,
    )
    opener = _FakeOpener([initialize, tools_list, initialize, tool_call])
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_args, **_kwargs: opener,
    )

    transport = StreamableHttpMcpTransport(
        (_HttpServer("fixture", "https://example.test/mcp"),)
    )
    assert [tool.name for tool in transport.model_tools] == ["mcp.fixture.echo"]

    response = transport.execute(
        McpProxyRequest(
            tool_call_id="call-1",
            target=parse_mcp_tool_name("mcp.fixture.echo"),
            arguments={"value": "zebra"},
        )
    )
    assert response.metadata["transport"] == "http"
    assert response.metadata["untrusted_output"] is True
    assert response.output == "UNTRUSTED MCP OUTPUT (fixture.echo)\necho:zebra"


def test_http_transport_resolves_bearer_token_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setenv("MCP_FIXTURE_BEARER_TOKEN", "secret-token")
    initialize = _rpc(
        {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}},
        request_id=1,
    )
    tools_list = _rpc({"tools": []}, request_id=2)
    opener = _FakeOpener([initialize, tools_list])
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_args, **_kwargs: opener,
    )

    StreamableHttpMcpTransport(
        (_HttpServer("fixture", "https://example.test/mcp", "MCP_FIXTURE_BEARER_TOKEN"),)
    )
    assert opener.last_request is not None
    assert opener.last_request.headers.get("Authorization") == "Bearer secret-token"


def test_http_transport_rejects_unsupported_protocol_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution",
        lambda *_args, **_kwargs: None,
    )
    initialize = _rpc(
        {"protocolVersion": "9999-99-99", "capabilities": {"tools": {}}},
        request_id=1,
    )
    opener = _FakeOpener([initialize])
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *_args, **_kwargs: opener,
    )
    with pytest.raises(McpProtocolError, match="unsupported protocol version"):
        StreamableHttpMcpTransport((_HttpServer("fixture", "https://example.test/mcp"),))
