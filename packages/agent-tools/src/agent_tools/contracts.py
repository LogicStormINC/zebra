from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from agent_core.domain.tools import ToolCall, ToolResult

ToolHandler = Callable[[ToolCall], ToolResult]


@dataclass(frozen=True)
class ToolContract:
    name: str
    required_arguments: tuple[str, ...] = ()
    description: str = ""
    argument_properties: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    parallel_safe: bool = False
    capability_version: str = "1"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool contract name must not be blank")
        normalized_required = tuple(argument.strip() for argument in self.required_arguments)
        if any(not argument for argument in normalized_required):
            raise ValueError("required argument names must not be blank")
        object.__setattr__(self, "required_arguments", normalized_required)
        if not isinstance(self.capability_version, str) or not self.capability_version.strip():
            raise ValueError("tool contract capability_version must not be blank")
        object.__setattr__(self, "capability_version", self.capability_version.strip())


@dataclass(frozen=True)
class RegisteredTool:
    contract: ToolContract
    handler: ToolHandler
    tags: tuple[str, ...] = field(default_factory=tuple)
