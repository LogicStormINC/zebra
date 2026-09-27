"""Durable client-effect suspension inside the tool loop.

Mirrors ``delegation_suspension`` for the browser plane: when a tool
result was deferred to a durable client effect, the loop freezes the
exact resume state into a ``CLIENT_EFFECT_SCHEDULED`` event, defers the
terminal tool event, and suspends the attempt as ``waiting_external_tool``.
The durable receipt later resumes the attempt with the real result
injected through the completed-tool continuation.
"""

from agent_core.domain.events import EventType
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)

CLIENT_EFFECT_DEFERRED = "client_effect_deferred"
CLIENT_EFFECT_ID = "client_effect_id"


def client_effect_suspension_result(
    context: HarnessContext,
    *,
    completion: ModelCompletion,
    messages: list[SessionMessage],
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
) -> HarnessAttemptResult | None:
    """Freeze resume state and suspend when tools deferred to the browser."""

    deferred = _deferred_effects(emitted_events, completion.tool_calls)
    if not deferred:
        return None
    effect_ids = [effect_id for _, effect_id in deferred]
    frozen_conversation = _conversation_before_deferred_results(messages, deferred)
    continuations = {
        effect_id: {
            "assistant_message": completion.assistant_message.content,
            "conversation": [
                message.model_dump(mode="json") for message in frozen_conversation
            ],
            "model_calls_used": model_calls_used,
            "tool_calls_executed": tool_calls_executed,
        }
        for _, effect_id in deferred
    }
    for draft in emitted_events:
        if draft.event_type is not EventType.CLIENT_EFFECT_SCHEDULED:
            continue
        if draft.payload.get("tool_call_id") not in {
            str(call.tool_call_id) for call, _ in deferred
        }:
            continue
        draft.payload.setdefault("assistant_message", completion.assistant_message.content)
        draft.payload.setdefault(
            "conversation",
            [message.model_dump(mode="json") for message in messages],
        )
        draft.payload.setdefault("model_calls_used", model_calls_used)
        draft.payload.setdefault("tool_calls_executed", tool_calls_executed)
    return build_attempt_result(
        outcome=HarnessAttemptOutcome.WAITING_EXTERNAL_TOOL,
        summary=("client effect scheduled; attempt waits for the durable browser receipt"),
        assistant_message=completion.assistant_message.content,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        emitted_events=emitted_events,
        metadata={
            **metadata,
            "stop_reason": "waiting_client_effect",
            "client_effect_ids": effect_ids,
            "client_effect_continuations": continuations,
        },
    )


def _deferred_effects(
    emitted_events: list[HarnessEventDraft],
    tool_calls: tuple[ToolCall, ...],
) -> list[tuple[ToolCall, str]]:
    """Pair scheduled client effects with their live ToolCall objects."""

    by_id = {str(call.tool_call_id): call for call in tool_calls}
    deferred: list[tuple[ToolCall, str]] = []
    seen: set[str] = set()
    for draft in emitted_events:
        if draft.event_type is not EventType.CLIENT_EFFECT_SCHEDULED:
            continue
        tool_call_id = draft.payload.get("tool_call_id")
        effect_id = draft.payload.get("client_effect_id")
        if not isinstance(tool_call_id, str) or tool_call_id not in by_id:
            continue
        if not isinstance(effect_id, str) or not effect_id.strip():
            continue
        if tool_call_id in seen:
            continue
        seen.add(tool_call_id)
        deferred.append((by_id[tool_call_id], effect_id.strip()))
    return deferred


def _conversation_before_deferred_results(
    messages: list[SessionMessage],
    deferred: list[tuple[ToolCall, str]],
) -> tuple[SessionMessage, ...]:
    call_ids = {
        call.provider_call_id or str(call.tool_call_id)
        for call, _ in deferred
    }
    end = len(messages)
    while (
        end
        and messages[end - 1].role is MessageRole.TOOL
        and messages[end - 1].tool_call_id in call_ids
    ):
        end -= 1
    return tuple(messages[:end])
