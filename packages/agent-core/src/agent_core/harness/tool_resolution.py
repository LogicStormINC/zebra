from collections.abc import Callable
from dataclasses import replace

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.models import HarnessContext, HarnessEventDraft
from agent_core.harness.protocol_invariants import HarnessInvariantError
from agent_core.harness.tool_recovery import reject_tool_batch

ToolCallResolver = Callable[[tuple[ToolCall, ...]], tuple[ToolCall, ...]]


def reject_invalid_bridge(
    context: HarnessContext, completion: ModelCompletion,
    messages: list[SessionMessage], emitted_events: list[HarnessEventDraft],
) -> None:
    messages.append(completion.assistant_message.model_copy(
        update={"tool_calls": completion.tool_calls}
    ))
    reject_tool_batch(
        completion.tool_calls, reason="Invalid tool bridge request. Check the tool schema.",
        messages=messages, created_at=context.attempt.started_at,
        attempt_number=context.attempt.number, emitted_events=emitted_events,
    )


def resolve_completion_tool_calls(
    completion: ModelCompletion,
    resolver: ToolCallResolver | None,
) -> ModelCompletion:
    if resolver is None or not completion.tool_calls:
        return completion
    resolved = resolver(completion.tool_calls)
    if len(resolved) != len(completion.tool_calls):
        raise HarnessInvariantError("tool call resolver changed the batch length")
    for original, current in zip(completion.tool_calls, resolved, strict=True):
        if (
            current.tool_call_id != original.tool_call_id
            or current.provider_call_id != original.provider_call_id
            or current.created_at != original.created_at
        ):
            raise HarnessInvariantError("tool call resolver changed immutable call identity")
    return replace(
        completion,
        tool_calls=resolved,
        assistant_message=completion.assistant_message.model_copy(update={"tool_calls": resolved}),
    )
