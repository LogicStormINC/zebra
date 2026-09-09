import asyncio
import json
import traceback
import urllib.request
from unittest.mock import Mock

import pytest
from agent_runtime.mcp_http import McpHttpSession
from agent_runtime.mcp_http_authorization import McpHttpBearerCredential
from agent_runtime.mcp_protocol import McpProtocolError
from agent_security.host_grant import HostGrantBindingError
from agent_security.secret_store import SecretMaterial

from tests.agent_runtime.test_mcp_http_streaming import Response, Server
from tests.agent_storage import test_mcp_credential_release as release_fixtures

protector = release_fixtures.protector
TOKEN = "fixture-private-bearer"


@pytest.fixture
def requests(monkeypatch):
    sent = []

    class Opener:
        def open(self, request, timeout):
            sent.append(request)
            payload = json.loads(request.data)
            result = {"content": []}
            if payload["method"] == "initialize":
                result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
            return Response({"jsonrpc": "2.0", "id": payload.get("id"), "result": result})

    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution", lambda *a, **kw: None
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    return sent


def credential(endpoint, token=TOKEN):
    return McpHttpBearerCredential(endpoint, SecretMaterial("ref", "fixture", value=token))


def test_every_frame_resolves_fresh_token_without_caching(requests):
    calls = []

    def resolve(endpoint, frame):
        calls.append(frame["method"])
        return credential(endpoint, f"{TOKEN}-{len(calls)}")

    with McpHttpSession(Server(), 1, credential_resolver=resolve) as session:
        session.request("tools/call", {"name": "search", "arguments": {}})
    assert calls == ["initialize", "notifications/initialized", "tools/call"]
    assert [r.get_header("Authorization") for r in requests] == [
        f"Bearer {TOKEN}-{i}" for i in range(1, 4)
    ]
    assert TOKEN not in repr(session) + repr(credential(Server().url))


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_denied_frame_never_sent_or_retried(requests, stage):
    count = 0

    def resolve(endpoint, frame):
        nonlocal count
        count += 1
        if count == stage:
            raise HostGrantBindingError(TOKEN)
        return credential(endpoint)

    with pytest.raises(McpProtocolError) as caught:
        with McpHttpSession(Server(), 1, credential_resolver=resolve) as session:
            session.request("tools/call", {"name": "search"})
    assert len(requests) == stage - 1 and count == stage
    assert TOKEN not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "token", [None, "bad\r\nInjected:value", "bad token", "非ASCII", "x" * 16385]
)
def test_invalid_tokens_fail_before_network(requests, token):
    with pytest.raises(McpProtocolError, match="authorization failed"):
        McpHttpSession(
            Server(), 1, credential_resolver=lambda endpoint, frame: credential(endpoint, token)
        ).request("initialize")
    assert requests == []


def test_wrong_endpoint_and_environment_mixing_are_rejected(requests, monkeypatch):
    resolve = Mock(return_value=credential("https://other.test/mcp"))
    with pytest.raises(McpProtocolError, match="authorization failed"):
        McpHttpSession(Server(), 1, credential_resolver=resolve).request("initialize")
    resolve.reset_mock()
    monkeypatch.setenv("MCP_FIXTURE_TOKEN", TOKEN)
    with pytest.raises(McpProtocolError, match="environment credentials"):
        McpHttpSession(
            Server(bearer_token_env="MCP_FIXTURE_TOKEN"), 1, credential_resolver=resolve
        ).request("initialize")
    resolve.assert_not_called()
    assert requests == []
    assert __import__("os").environ["MCP_FIXTURE_TOKEN"] == TOKEN


def test_resolver_cannot_mutate_serialized_request_or_pinned_endpoint(requests):
    server = Server()

    def resolve(endpoint, frame):
        frame["method"] = "tools/delete"
        server.url = "https://other.test/mcp"
        return credential(endpoint)

    McpHttpSession(server, 1, credential_resolver=resolve).request("tools/list")
    assert requests[0].full_url == "https://example.test/mcp"
    assert json.loads(requests[0].data)["method"] == "tools/list"


def test_separate_sessions_never_share_credentials(requests):
    for user in ("alice", "bob"):
        McpHttpSession(
            Server(),
            1,
            credential_resolver=lambda endpoint, frame, user=user: credential(endpoint, user),
        ).request("tools/list")
    assert [r.get_header("Authorization") for r in requests] == ["Bearer alice", "Bearer bob"]


def test_internal_release_connects_to_transport_and_revocation_stops_call(requests, protector):
    service, args, _ = release_fixtures.runtime(protector)

    def resolve(endpoint, frame):
        return McpHttpBearerCredential(endpoint, asyncio.run(service.release(**args)))

    with McpHttpSession(Server(), 1, credential_resolver=resolve) as session:
        service.store.get_for_use.side_effect = HostGrantBindingError("revoked")
        with pytest.raises(McpProtocolError, match="authorization failed"):
            session.request("tools/call", {"name": "search", "arguments": {}})
    assert [json.loads(r.data)["method"] for r in requests] == [
        "initialize",
        "notifications/initialized",
    ]
    assert service.store.get_for_use.call_count == 3


def test_network_error_does_not_leak_credentials_or_replay(requests, monkeypatch):
    opener = Mock()
    opener.open.side_effect = OSError(TOKEN)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: opener)
    with pytest.raises(McpProtocolError) as caught:
        McpHttpSession(
            Server(), 1, credential_resolver=lambda endpoint, frame: credential(endpoint)
        ).request("tools/call", {"name": "search"})
    assert opener.open.call_count == 1
    assert TOKEN not in "".join(traceback.format_exception(caught.value))


def test_legacy_environment_path_unchanged(requests, monkeypatch):
    monkeypatch.setenv("MCP_FIXTURE_TOKEN", TOKEN)
    McpHttpSession(Server(bearer_token_env="MCP_FIXTURE_TOKEN"), 1).request("tools/list")
    assert requests[0].get_header("Authorization") == f"Bearer {TOKEN}"
