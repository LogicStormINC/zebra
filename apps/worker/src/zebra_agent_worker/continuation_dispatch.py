"""Dispatch one continuation kind onto the harness orchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.models import HarnessAttemptResult, HarnessContext

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.clarification_continuation import ClarificationContinuation

if TYPE_CHECKING:
    from agent_core.harness.orchestrator import SingleAttemptOrchestrator


def run_continuation(
    orchestrator: SingleAttemptOrchestrator,
    context: HarnessContext,
    *,
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
) -> HarnessAttemptResult:
    if continuation is not None and continuation.completed_output is not None:
        return orchestrator.continue_completed_tool(
            context,
            completion=continuation.completion,
            tool_call=continuation.tool_call,
            tool_result=ToolResult(
                tool_call_id=continuation.tool_call.tool_call_id,
                status=(
                    ToolCallStatus.EXECUTED
                    if continuation.completed_status == "executed"
                    else ToolCallStatus.FAILED
                ),
                output=continuation.completed_output,
                metadata=dict(continuation.completed_metadata or {}),
            ),
            conversation=continuation.conversation,
            model_calls_used=continuation.model_calls_used,
            tool_calls_executed=continuation.tool_calls_executed,
            assistant_message=continuation.completion.assistant_message.content,
        )
    if continuation is not None:
        return orchestrator.continue_approved_tool_call(
            context,
            initial_completion=continuation.completion,
            tool_call=continuation.tool_call,
            remaining_tool_calls=continuation.remaining_tool_calls,
            conversation=continuation.conversation,
            model_calls_used=continuation.model_calls_used,
            tool_calls_executed=continuation.tool_calls_executed,
        )
    if clarification is not None:
        return orchestrator.continue_clarification(
            context,
            tool_call=clarification.tool_call,
            response=clarification.response,
            conversation=clarification.conversation,
            model_calls_used=clarification.model_calls_used,
            tool_calls_executed=clarification.tool_calls_executed,
            assistant_message=clarification.assistant_message,
        )
    return orchestrator.run(context)
