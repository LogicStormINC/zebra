"""Durable delegation suspension inside the tool loop (plan 8.2/8.4).

When a tool result carries ``suspend_after_turn`` the parent does not
finish its turn pretending to hold a result: the loop freezes the exact
join state (conversation, counters, tool-call identity) into a
``SUBAGENT_DELEGATED`` event and suspends the attempt. The child's
durable wakeup later resumes the parent with the real result injected
through the completed-tool continuation.
"""

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)

SUSPEND_AFTER_TURN = "suspend_after_turn"
CHILD_TASK_ID = "child_task_id"


def delegation_suspension_result(
    context: HarnessContext,
    *,
    completion: ModelCompletion,
    messages: list[SessionMessage],
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
) -> HarnessAttemptResult | None:
    """Freeze join state and suspend when a tool delegated durably."""

    delegated = _delegated_calls(emitted_events, completion.tool_calls)
    if not delegated:
        return None
    child_task_ids: list[str] = []
    for tool_call, child_task_id in delegated:
        child_task_ids.append(child_task_id)
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.SUBAGENT_DELEGATED,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": context.attempt.number,
                    "child_task_id": child_task_id,
                    "tool_name": tool_call.name,
                    "tool_call_id": str(tool_call.tool_call_id),
                    "arguments": tool_call.arguments,
                    "assistant_message": completion.assistant_message.content,
                    "conversation": [
                        message.model_dump(mode="json") for message in messages
                    ],
                    "model_calls_used": model_calls_used,
                    "tool_calls_executed": tool_calls_executed,
                    **(
                        {"provider_call_id": tool_call.provider_call_id}
                        if tool_call.provider_call_id is not None
                        else {}
                    ),
                },
            )
        )
    return build_attempt_result(
        outcome=HarnessAttemptOutcome.SUSPENDED,
        summary=(
            "durable delegation materialized; attempt suspended until the "
            "child wakeup arrives"
        ),
        assistant_message=completion.assistant_message.content,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        emitted_events=emitted_events,
        metadata={
            **metadata,
            "stop_reason": "waiting_children",
            "child_task_ids": child_task_ids,
        },
    )


def _delegated_calls(
    emitted_events: list[HarnessEventDraft],
    tool_calls: tuple[ToolCall, ...],
) -> list[tuple[ToolCall, str]]:
    """Pair delegated tool results with their live ToolCall objects."""

    by_id = {str(call.tool_call_id): call for call in tool_calls}
    delegated: list[tuple[ToolCall, str]] = []
    seen: set[str] = set()
    for draft in emitted_events:
        if draft.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
            continue
        result_metadata = draft.payload.get("metadata")
        if not isinstance(result_metadata, dict):
            continue
        if result_metadata.get(SUSPEND_AFTER_TURN) is not True:
            continue
        child_task_id = result_metadata.get(CHILD_TASK_ID)
        tool_call_id = draft.payload.get("tool_call_id")
        if not isinstance(child_task_id, str) or not child_task_id.strip():
            continue
        if not isinstance(tool_call_id, str) or tool_call_id not in by_id:
            continue
        if tool_call_id in seen:
            continue
        seen.add(tool_call_id)
        delegated.append((by_id[tool_call_id], child_task_id.strip()))
    return delegated
