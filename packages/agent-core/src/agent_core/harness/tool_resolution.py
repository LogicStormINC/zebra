from collections.abc import Callable
from dataclasses import replace

from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall

ToolCallResolver = Callable[[tuple[ToolCall, ...]], tuple[ToolCall, ...]]


def resolve_completion_tool_calls(
    completion: ModelCompletion,
    resolver: ToolCallResolver | None,
) -> ModelCompletion:
    if resolver is None or not completion.tool_calls:
        return completion
    resolved = resolver(completion.tool_calls)
    if len(resolved) != len(completion.tool_calls):
        raise ValueError("tool call resolver changed the batch length")
    for original, current in zip(completion.tool_calls, resolved, strict=True):
        if (
            current.tool_call_id != original.tool_call_id
            or current.provider_call_id != original.provider_call_id
            or current.created_at != original.created_at
        ):
            raise ValueError("tool call resolver changed immutable call identity")
    return replace(
        completion,
        tool_calls=resolved,
        assistant_message=completion.assistant_message.model_copy(
            update={"tool_calls": resolved}
        ),
    )
