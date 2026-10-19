"""Shared terminal construction and paired results for a revoked plugin source."""

from typing import TYPE_CHECKING

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.plugin_authority import PLUGIN_UNAVAILABLE, plugin_unavailable_result
from agent_core.domain.tools import ToolCall
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.model_step_support import tool_result_message
from agent_core.harness.models import HarnessAttemptOutcome, HarnessContext, HarnessEventDraft

if TYPE_CHECKING:
    from agent_core.harness.concurrent_batch import ToolBatchResult


def terminal_batch_result(
    *,
    outcome: HarnessAttemptOutcome,
    summary: str,
    completion: ModelCompletion,
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
) -> "ToolBatchResult":
    from agent_core.harness.concurrent_batch import ToolBatchResult

    return ToolBatchResult(
        build_attempt_result(
            outcome=outcome,
            summary=summary,
            assistant_message=completion.assistant_message.content,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            emitted_events=emitted_events,
            metadata=metadata,
        ),
        tool_calls_executed,
        metadata,
    )


def plugin_stop(
    *,
    context: HarnessContext,
    remaining: tuple[ToolCall, ...],
    messages: list[SessionMessage],
    completion: ModelCompletion,
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
) -> "ToolBatchResult":
    for call in remaining:
        result = plugin_unavailable_result(call)
        messages.append(tool_result_message(call, result, created_at=context.attempt.started_at))
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_FAILED,
                actor=EventActor.TOOL,
                payload={
                    "attempt_number": context.attempt.number,
                    "tool_name": call.name,
                    "tool_call_id": str(call.tool_call_id),
                    "status": result.status.value,
                    "output": result.output,
                    "metadata": result.metadata,
                },
            )
        )
    return terminal_batch_result(
        outcome=HarnessAttemptOutcome.SUSPENDED,
        summary="Accepted plugin authority is unavailable; execution suspended.",
        completion=completion,
        emitted_events=emitted_events,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        metadata={**metadata, "stop_reason": PLUGIN_UNAVAILABLE, "retryable": False},
    )
