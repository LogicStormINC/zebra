from typing import Protocol

from agent_core.domain.tools import ToolCall, ToolResult


class ToolGatewayPort(Protocol):
    def execute(self, tool_call: ToolCall) -> ToolResult: ...
