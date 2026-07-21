from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from agent_runtime import LocalStdioMcpTransport
from agent_runtime.mcp_pool import McpHealthState, McpSessionPool
from agent_runtime.mcp_routing import build_mcp_transport
from agent_tools import McpProxyRequest, parse_mcp_tool_name


@dataclass(frozen=True)
class _Server:
    name: str
    command: str
    args: tuple[str, ...]


def _server() -> _Server:
    script = Path(__file__).parents[1] / "fixtures" / "mcp_stdio_server.py"
    return _Server(name="fixture", command=sys.executable, args=(str(script), "normal"))


def test_pool_wraps_stdio_transport_and_stays_healthy() -> None:
    transport = LocalStdioMcpTransport((_server(),))
    pool = McpSessionPool(transport)

    response = pool.execute(
        McpProxyRequest(
            tool_call_id="call-1",
            target=parse_mcp_tool_name("mcp.fixture.echo"),
            arguments={"value": "zebra"},
        )
    )
    assert "echo:zebra" in response.output
    assert pool.health is McpHealthState.HEALTHY
    assert [tool.name for tool in pool.model_tools] == ["mcp.fixture.echo"]
    pool.close()


def test_build_mcp_transport_wraps_subtransports_in_a_pool() -> None:
    transport = build_mcp_transport((_server(),), None, max_output_bytes=None)
    # The harness path now wraps each sub-transport in a session pool so health
    # and backoff are active (not a raw LocalStdioMcpTransport).
    assert isinstance(transport, McpSessionPool)
    assert [tool.name for tool in transport.model_tools] == ["mcp.fixture.echo"]
    response = transport.execute(
        McpProxyRequest(
            tool_call_id="call-1",
            target=parse_mcp_tool_name("mcp.fixture.echo"),
            arguments={"value": "zebra"},
        )
    )
    assert "echo:zebra" in response.output
    assert transport.health is McpHealthState.HEALTHY
    transport.close()
