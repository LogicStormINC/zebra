from dataclasses import dataclass, field
from typing import Protocol

from agent_core.domain.tools import ToolCall


@dataclass(frozen=True)
class ToolCallSelection:
    tool_call: ToolCall
    summary: str
    metadata: dict[str, object] = field(default_factory=dict)


class ToolCallSelectionStrategy(Protocol):
    def select(self, tool_calls: tuple[ToolCall, ...]) -> ToolCallSelection:
        """Select one tool call from a model completion."""


class FirstToolCallSelectionStrategy:
    def select(self, tool_calls: tuple[ToolCall, ...]) -> ToolCallSelection:
        if not tool_calls:
            raise ValueError("tool_calls must not be empty")
        tool_call = tool_calls[0]
        return ToolCallSelection(
            tool_call=tool_call,
            summary="selected first tool call",
            metadata={
                "selected_index": 0,
                "candidate_count": len(tool_calls),
            },
        )
