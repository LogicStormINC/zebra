from __future__ import annotations

from collections.abc import Sequence

from agent_core.domain.modeling import ModelToolDefinition
from agent_tools import McpProxyRequest, McpProxyResponse

from agent_runtime.mcp_http import StreamableHttpMcpTransport
from agent_runtime.mcp_protocol import McpAnyServerSpec, McpHttpServerSpec, McpProtocolError
from agent_runtime.mcp_stdio import LocalStdioMcpTransport


class _CompositeMcpTransport:
    """Unions stdio + HTTP sub-transports and routes calls by server name.

    Each sub-transport already enforces its own allowlist over its discovered
    tools, so the composite only unions ``model_tools`` and dispatches
    ``execute`` to the owning sub-transport.
    """

    def __init__(
        self,
        transports: Sequence[LocalStdioMcpTransport | StreamableHttpMcpTransport],
    ) -> None:
        self._transports = tuple(transports)
        routes: dict[str, LocalStdioMcpTransport | StreamableHttpMcpTransport] = {}
        combined: list[ModelToolDefinition] = []
        for transport in self._transports:
            for tool in transport.model_tools:
                server = _server_of(tool.name)
                if server is not None:
                    routes[server] = transport
                combined.append(tool)
        self._routes = routes
        self.model_tools = tuple(sorted(combined, key=lambda item: item.name))

    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        transport = self._routes.get(request.target.server_name)
        if transport is None:
            raise McpProtocolError("MCP tool is not in the configured discovery catalog")
        return transport.execute(request)


def build_mcp_transport(
    servers: Sequence[McpAnyServerSpec],
    allowlist: Sequence[str] | None,
    *,
    max_output_bytes: int | None,
) -> LocalStdioMcpTransport | StreamableHttpMcpTransport | _CompositeMcpTransport | None:
    """Build the effective MCP transport(s), partitioning servers by kind.

    Returns ``None`` when there are no servers or the allowlist is empty, mirroring
    the original stdio-only guard.
    """
    if not servers or (allowlist is not None and not allowlist):
        return None
    stdio_servers = [server for server in servers if not isinstance(server, McpHttpServerSpec)]
    http_servers = [server for server in servers if isinstance(server, McpHttpServerSpec)]
    stdio_allowlist, http_allowlist = _partition_allowlist(
        allowlist, stdio_servers, http_servers
    )
    transports: list[LocalStdioMcpTransport | StreamableHttpMcpTransport] = []
    if stdio_servers:
        transports.append(
            LocalStdioMcpTransport(
                stdio_servers,
                stdio_allowlist,
                max_output_bytes=max_output_bytes,
            )
        )
    if http_servers:
        transports.append(
            StreamableHttpMcpTransport(
                http_servers,
                http_allowlist,
                max_output_bytes=max_output_bytes,
            )
        )
    if not transports:
        return None
    if len(transports) == 1:
        return transports[0]
    return _CompositeMcpTransport(transports)


def _partition_allowlist(
    allowlist: Sequence[str] | None,
    stdio_servers: Sequence[McpAnyServerSpec],
    http_servers: Sequence[McpHttpServerSpec],
) -> tuple[Sequence[str] | None, Sequence[str] | None]:
    if allowlist is None:
        return None, None
    http_names = {server.name for server in http_servers}
    configured = {server.name for server in [*stdio_servers, *http_servers]}
    stdio_tools: list[str] = []
    http_tools: list[str] = []
    orphan_tools: list[str] = []
    for name in allowlist:
        server = _server_of(name)
        if server in http_names:
            http_tools.append(name)
        elif server in configured:
            stdio_tools.append(name)
        else:
            orphan_tools.append(name)
    if orphan_tools:
        raise McpProtocolError(
            f"selected MCP tools are unavailable: {', '.join(sorted(set(orphan_tools)))}"
        )
    return tuple(stdio_tools), tuple(http_tools)


def _server_of(tool_name: str) -> str | None:
    parts = tool_name.split(".")
    if len(parts) >= 2 and parts[0] == "mcp":
        return parts[1]
    return None
