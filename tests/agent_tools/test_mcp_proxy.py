from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_tools.errors import ToolArgumentError
from agent_tools.mcp_proxy import (
    McpProxyRequest,
    McpProxyResponse,
    McpProxyTransport,
    build_mcp_proxy_request,
    parse_mcp_tool_name,
)


def test_parse_mcp_tool_name_returns_target() -> None:
    target = parse_mcp_tool_name("mcp.github.create_pull_request")

    assert target.server_name == "github"
    assert target.tool_name == "create_pull_request"


def test_parse_mcp_tool_name_rejects_invalid_name() -> None:
    with pytest.raises(ToolArgumentError, match="mcp.<server>.<tool>"):
        parse_mcp_tool_name("github.create_pull_request")


def test_build_mcp_proxy_request_normalizes_serializable_shape() -> None:
    request = build_mcp_proxy_request(
        _tool_call(
            "mcp.github.create_pull_request",
            {
                "title": "Add feature",
                "reviewers": ["alice", "bob"],
            },
        ),
        metadata={"route": "mcp_proxy", "network_profile": "mcp-proxy-only"},
    )

    assert request.to_serializable() == {
        "tool_call_id": str(request.tool_call_id),
        "server_name": "github",
        "tool_name": "create_pull_request",
        "arguments": {
            "reviewers": ["alice", "bob"],
            "title": "Add feature",
        },
        "metadata": {
            "network_profile": "mcp-proxy-only",
            "route": "mcp_proxy",
        },
    }


def test_build_mcp_proxy_request_rejects_non_json_arguments() -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):
        build_mcp_proxy_request(
            _tool_call("mcp.github.create_pull_request", {"payload": object()}),
        )


def test_mcp_proxy_transport_protocol_accepts_fake() -> None:
    transport = _FakeMcpProxyTransport()

    typed_transport: McpProxyTransport = transport

    response = typed_transport.execute(
        McpProxyRequest(
            tool_call_id="call-123",
            target=parse_mcp_tool_name("mcp.github.create_pull_request"),
            arguments={"title": "Add feature"},
        )
    )

    assert isinstance(response, McpProxyResponse)
    assert response.output == "ok"


def _tool_call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 6, 28, 12, 0, tzinfo=UTC),
    )


class _FakeMcpProxyTransport:
    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        assert request.target.server_name == "github"
        return McpProxyResponse(output="ok", metadata={"transport": "fake"})
