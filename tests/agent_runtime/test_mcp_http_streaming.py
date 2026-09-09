import io
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import pytest
from agent_runtime.mcp_http import McpHttpSession
from agent_runtime.mcp_http_response import read_response
from agent_runtime.mcp_protocol import MAX_MCP_FRAME_BYTES, McpProtocolError


def frame(message: dict) -> bytes:
    return b"data: " + json.dumps(message).encode() + b"\n\n"


def test_progress_then_result_returns_without_waiting_for_eof() -> None:
    class OpenStream(io.BytesIO):
        def readline(self, size=-1):
            assert self.tell() < len(self.getvalue()), "must not wait for EOF"
            return super().readline(size)

    stream = OpenStream(
        b": heartbeat\n\nid: cursor\ndata:\n\n"
        + frame({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}})
        + frame({"jsonrpc": "2.0", "id": 7, "result": {"content": []}})
    )
    assert read_response(stream, "text/event-stream", 7, time.monotonic() + 1)["result"] == {
        "content": []
    }


@pytest.mark.parametrize(
    "body",
    [
        frame({"jsonrpc": "2.0", "id": 8, "result": {}}),
        frame({"jsonrpc": "2.0", "id": True, "result": {}}),
        frame({"jsonrpc": "2.0", "id": 7, "result": {}, "error": {}}),
        frame({"jsonrpc": "2.0", "id": 7, "method": "sampling/createMessage"}),
        b"data: broken\n\n",
        b"data: \xff\n\n",
        b":" + b"x" * MAX_MCP_FRAME_BYTES,
        b"data: {}",
    ],
)
def test_invalid_or_incomplete_stream_fails(body: bytes) -> None:
    with pytest.raises(McpProtocolError):
        read_response(io.BytesIO(body), "text/event-stream", 7, time.monotonic() + 1)


def test_multiline_data_and_crlf() -> None:
    stream = io.BytesIO(b'data: {"jsonrpc":"2.0",\r\ndata: "id":7,"result":{}}\r\n\r\n')
    assert read_response(stream, "text/event-stream", 7, time.monotonic() + 1)["id"] == 7


@dataclass
class Server:
    name: str = "fixture"
    url: str = "https://example.test/mcp"
    bearer_token_env: str | None = None


class Response(io.BytesIO):
    def __init__(self, payload: dict, session: str | None = None):
        super().__init__(json.dumps(payload).encode())
        self.headers = {"Content-Type": "application/json"}
        if session is not None:
            self.headers["MCP-Session-Id"] = session


@pytest.mark.parametrize("session", ["private-session", "bad\r\nSECRET", "", "x" * 4097])
def test_session_header_is_validated_and_propagated(monkeypatch, session):
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            payload = json.loads(request.data)
            if payload["method"] == "initialize":
                return Response(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"protocolVersion": "2025-11-25", "capabilities": {}},
                    },
                    session,
                )
            return Response({"jsonrpc": "2.0", "id": payload.get("id"), "result": {}})

    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution", lambda *a, **kw: None
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    instance = McpHttpSession(Server(), 1)
    if session != "private-session":
        with pytest.raises(McpProtocolError, match="invalid session header"):
            instance.__enter__()
        return
    with instance:
        instance.request("tools/list")
    assert len(requests) == 3
    assert all(r.get_header("Mcp-session-id") == session for r in requests[1:])
    assert all(r.get_header("Mcp-protocol-version") == "2025-11-25" for r in requests[1:])
    assert session not in repr(instance)
    assert McpHttpSession(Server(), 1)._session_id is None


def test_initialized_failure_stops_handshake(monkeypatch):
    methods = []

    class Opener:
        def open(self, request, timeout):
            methods.append(json.loads(request.data)["method"])
            if len(methods) == 1:
                return Response(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"protocolVersion": "2025-11-25", "capabilities": {}},
                    }
                )
            raise OSError("SECRET backend detail")

    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution", lambda *a, **kw: None
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(McpProtocolError) as caught:
        with McpHttpSession(Server(), 1):
            pytest.fail("handshake must fail")
    assert "SECRET" not in str(caught.value)
    assert methods == ["initialize", "notifications/initialized"]
