from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult

from agent_tools.mcp_proxy import McpProxyTransport, build_mcp_proxy_request


@dataclass(frozen=True)
class McpProxyToolGateway:
    transport: McpProxyTransport

    def execute(self, tool_call: ToolCall) -> ToolResult:
        request = build_mcp_proxy_request(
            tool_call,
            metadata={"route": "mcp_proxy"},
        )
        response = self.transport.execute(request)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=response.output,
            metadata={
                "route": "mcp_proxy",
                "server_name": request.target.server_name,
                "tool_name": request.target.tool_name,
                **response.metadata,
            },
        )
