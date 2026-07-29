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
        operation_key = _operation_key_for(self.transport, request)
        try:
            response = self.transport.execute(request)
        except ValueError as exc:
            metadata: dict[str, object] = {
                "route": "proxy",
                "proxy_target": (
                    f"{request.target.server_name}.{request.target.tool_name}"
                ),
                "proxy_transport": "mcp_proxy",
                "reason": "mcp_proxy_error",
                "detail": str(exc),
            }
            if operation_key is not None:
                metadata["operation_key"] = operation_key
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output="",
                metadata=metadata,
            )
        failed = response.metadata.get("mcp_is_error") is True
        metadata = {
            "route": "proxy",
            "proxy_target": f"{request.target.server_name}.{request.target.tool_name}",
            "proxy_transport": "mcp_proxy",
            "server_name": request.target.server_name,
            "tool_name": request.target.tool_name,
            **response.metadata,
        }
        if operation_key is not None:
            metadata["operation_key"] = operation_key
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED if failed else ToolCallStatus.EXECUTED,
            output=response.output,
            metadata=metadata,
        )


def _operation_key_for(
    transport: McpProxyTransport,
    request: object,
) -> str | None:
    provider = getattr(transport, "operation_key_for", None)
    if not callable(provider):
        return None
    value = provider(request)
    return value if isinstance(value, str) and value else None
