from agent_core.domain.tools import ToolCall, ToolResult

from agent_tools.errors import ToolArgumentError
from agent_tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, tool_call: ToolCall) -> ToolResult:
        registered = self._registry.get(tool_call.name)
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
