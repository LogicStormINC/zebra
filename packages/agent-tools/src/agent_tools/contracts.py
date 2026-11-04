from collections.abc import Callable
from dataclasses import dataclass, field

from agent_core.domain.tools import (
    MAX_TOOL_OUTPUT_BYTES,
    MAX_TOOL_SCOPES,
    MAX_TOOL_TIMEOUT_SECONDS,
    ToolCall,
    ToolContract,
    ToolExecutionLocation,
    ToolIdempotency,
    ToolReceipt,
    ToolResult,
    ToolRisk,
)

ToolHandler = Callable[[ToolCall], ToolResult]

__all__ = [
    "MAX_TOOL_OUTPUT_BYTES",
    "MAX_TOOL_SCOPES",
    "MAX_TOOL_TIMEOUT_SECONDS",
    "RegisteredTool",
    "ToolContract",
    "ToolExecutionLocation",
    "ToolHandler",
    "ToolIdempotency",
    "ToolReceipt",
    "ToolRisk",
]


@dataclass(frozen=True)
class RegisteredTool:
    contract: ToolContract
    handler: ToolHandler
    tags: tuple[str, ...] = field(default_factory=tuple)
