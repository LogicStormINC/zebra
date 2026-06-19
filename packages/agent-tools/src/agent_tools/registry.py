from agent_tools.contracts import RegisteredTool, ToolContract, ToolHandler
from agent_tools.errors import ToolRegistryError, UnknownToolError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        contract: ToolContract,
        handler: ToolHandler,
        *,
        tags: tuple[str, ...] = (),
    ) -> RegisteredTool:
        if contract.name in self._tools:
            raise ToolRegistryError(f"tool is already registered: {contract.name}")

        registered = RegisteredTool(contract=contract, handler=handler, tags=tags)
        self._tools[contract.name] = registered
        return registered

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"unknown tool: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))
