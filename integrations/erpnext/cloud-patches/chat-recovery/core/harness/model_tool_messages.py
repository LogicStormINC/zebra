"""Deterministic tool-call and tool-result message construction."""

from datetime import datetime

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.harness.model_step_support import tool_result_message


def append_tool_batch(
    messages: list[SessionMessage],
    *,
    completion: ModelCompletion,
    tool_calls: tuple[ToolCall, ...],
) -> None:
    if not tool_calls:
        raise ValueError("tool batch must not be empty")
    messages.append(completion.assistant_message.model_copy(update={"tool_calls": tool_calls}))


def append_tool_result(
    messages: list[SessionMessage],
    *,
    tool_call: ToolCall,
    tool_result: ToolResult,
    created_at: datetime,
) -> None:
    messages.append(tool_result_message(tool_call, tool_result, created_at=created_at))
