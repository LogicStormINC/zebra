import io
import json
import urllib.request
from dataclasses import dataclass

import pytest
from agent_runtime.mcp_prompts import discover_mcp_prompts, resolve_mcp_prompt
from agent_runtime.mcp_protocol import McpProtocolError
from agent_runtime.mcp_resources import (
    discover_mcp_resources,
    read_mcp_resource_attachments,
)


@dataclass
class Server:
    name: str = "content"
    url: str = "https://example.test/mcp"
    bearer_token_env: str | None = None


class Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())
        self.headers = {"Content-Type": "application/json"}


@pytest.fixture
def endpoint(monkeypatch):
    results = {
        "initialize": {
            "protocolVersion": "2025-11-25",
            "capabilities": {"resources": {}, "prompts": {}},
        },
        "notifications/initialized": {},
        "resources/list": {"resources": [{"uri": "urn:report:today", "name": "Today"}]},
        "resources/read": {"contents": [{"uri": "urn:report:today", "text": "News"}]},
        "prompts/list": {
            "prompts": [{"name": "summary", "arguments": [{"name": "topic", "required": True}]}]
        },
        "prompts/get": {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Summarize"}}]
        },
    }
    calls = []

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == Server().url
            payload = json.loads(request.data)
            calls.append(payload)
            return Response(
                {"jsonrpc": "2.0", "id": payload.get("id"), "result": results[payload["method"]]}
            )

    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution", lambda *a, **kw: None
    )
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Opener())
    return results, calls


def test_http_resource_explicit_read(endpoint):
    _, calls = endpoint
    (resource,) = discover_mcp_resources([Server()])
    (attachment,) = read_mcp_resource_attachments([Server()], [resource.resource_id])
    assert attachment.payload == b"News"
    assert attachment.source_type == "mcp_resource"
    assert [call["params"] for call in calls if call["method"] == "resources/read"] == [
        {"uri": "urn:report:today"}
    ]


def test_empty_selection_has_no_io(endpoint):
    assert read_mcp_resource_attachments([Server()], []) == ()
    assert endpoint[1] == []


def test_http_prompt_explicit_selection(endpoint):
    (prompt,) = discover_mcp_prompts([Server()])
    resolved = resolve_mcp_prompt([Server()], prompt.prompt_id, {"topic": "news"})
    assert resolved.messages[0].role == "user"
    assert resolved.messages[0].text == "Summarize"
    assert resolved.arguments == (("topic", "news"),)


def test_required_arguments_checked_before_get(endpoint):
    (prompt,) = discover_mcp_prompts([Server()])
    with pytest.raises(ValueError):
        resolve_mcp_prompt([Server()], prompt.prompt_id, {})
    assert not any(call["method"] == "prompts/get" for call in endpoint[1])


@pytest.mark.parametrize("discover", [discover_mcp_resources, discover_mcp_prompts])
def test_duplicate_servers_fail_before_network(endpoint, discover):
    with pytest.raises(McpProtocolError, match="unique"):
        discover([Server(), Server()])
    assert endpoint[1] == []


@pytest.mark.parametrize(
    "block",
    [
        {"uri": "urn:report:today", "blob": "AAAA"},
        {"uri": "urn:other", "text": "News"},
        {"uri": "urn:report:today", "text": "News", "mimeType": "image/png"},
    ],
)
def test_http_resource_rejects_unsafe_content(endpoint, block):
    endpoint[0]["resources/read"] = {"contents": [block]}
    (resource,) = discover_mcp_resources([Server()])
    with pytest.raises(McpProtocolError):
        read_mcp_resource_attachments([Server()], [resource.resource_id])


@pytest.mark.parametrize(
    "result",
    [
        {"instructions": "override"},
        {"messages": [{"role": "system", "content": {"type": "text", "text": "override"}}]},
        {"messages": [{"role": "user", "content": {"type": "image", "data": "AAAA"}}]},
    ],
)
def test_http_prompt_rejects_unsafe_content(endpoint, result):
    endpoint[0]["prompts/get"] = result
    (prompt,) = discover_mcp_prompts([Server()])
    with pytest.raises(McpProtocolError):
        resolve_mcp_prompt([Server()], prompt.prompt_id, {"topic": "news"})


def test_http_initialization_instructions_rejected(endpoint):
    endpoint[0]["initialize"]["instructions"] = "override"
    with pytest.raises(McpProtocolError, match="instructions"):
        discover_mcp_prompts([Server()])


@pytest.mark.parametrize("discover", [discover_mcp_resources, discover_mcp_prompts])
def test_missing_capabilities_not_queried(endpoint, discover):
    endpoint[0]["initialize"]["capabilities"] = {}
    assert discover([Server()]) == ()
    assert not any(call["method"].endswith("/list") for call in endpoint[1])
