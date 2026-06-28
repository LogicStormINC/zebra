from agent_core.domain.tools import ToolCall, ToolResult

from agent_tools.errors import ToolArgumentError, UnknownToolError
from agent_tools.mcp_gateway import McpProxyToolGateway
from agent_tools.mcp_proxy import parse_mcp_tool_name
from agent_tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        mcp_proxy_gateway: McpProxyToolGateway | None = None,
    ) -> None:
        self._registry = registry
        self._mcp_proxy_gateway = mcp_proxy_gateway

    def execute(self, tool_call: ToolCall) -> ToolResult:
        try:
            registered = self._registry.get(tool_call.name)
        except UnknownToolError:
            if self._mcp_proxy_gateway is not None and _is_mcp_tool_name(tool_call.name):
                return self._mcp_proxy_gateway.execute(tool_call)
            raise
        self._validate_arguments(tool_call, registered.contract.required_arguments)
        return registered.handler(tool_call)

    @staticmethod
    def _validate_arguments(tool_call: ToolCall, required_arguments: tuple[str, ...]) -> None:
        missing = [
            argument
            for argument in required_arguments
            if argument not in tool_call.arguments
        ]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ToolArgumentError(f"missing required arguments for {tool_call.name}: {joined}")


def _is_mcp_tool_name(tool_name: str) -> bool:
    try:
        parse_mcp_tool_name(tool_name)
    except ToolArgumentError:
        return False
    return True
