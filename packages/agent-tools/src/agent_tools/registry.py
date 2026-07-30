from agent_core.domain.modeling import ModelToolDefinition

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

    def parallel_safe_names(self) -> frozenset[str]:
        return frozenset(name for name, tool in self._tools.items() if tool.contract.parallel_safe)

    def names_with_tag(self, tag: str) -> frozenset[str]:
        return frozenset(name for name, tool in self._tools.items() if tag in tool.tags)

    def model_tools(self) -> tuple[ModelToolDefinition, ...]:
        definitions: list[ModelToolDefinition] = []
        for name in self.names():
            contract = self._tools[name].contract
            properties = {
                argument: dict(contract.argument_properties.get(argument, {}))
                for argument in sorted(
                    set(contract.argument_properties) | set(contract.required_arguments)
                )
            }
            definitions.append(
                ModelToolDefinition(
                    name=contract.name,
                    description=contract.description or f"Execute {contract.name}.",
                    parameters={
                        "type": "object",
                        "properties": properties,
                        "required": list(contract.required_arguments),
                        "additionalProperties": False,
                    },
                )
            )
        return tuple(definitions)
