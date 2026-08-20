"""Dispatch one continuation kind onto the harness orchestrator."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.models import HarnessAttemptResult, HarnessContext

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.child_wakeup_continuation import ChildWakeupContinuation
from zebra_agent_worker.clarification_continuation import ClarificationContinuation

if TYPE_CHECKING:
    from agent_core.harness.orchestrator import SingleAttemptOrchestrator


def run_continuation(
    orchestrator: SingleAttemptOrchestrator,
    context: HarnessContext,
    *,
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
    child_wakeup: ChildWakeupContinuation | None = None,
) -> HarnessAttemptResult:
    if child_wakeup is not None:
        return orchestrator.continue_completed_tool(
            context,
            completion=child_wakeup_completion(child_wakeup),
            tool_call=child_wakeup.tool_call,
            tool_result=child_wakeup_tool_result(child_wakeup),
            conversation=child_wakeup.conversation,
            model_calls_used=child_wakeup.model_calls_used,
            tool_calls_executed=child_wakeup.tool_calls_executed,
            assistant_message=child_wakeup.assistant_message,
        )
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


def child_wakeup_completion(child_wakeup: ChildWakeupContinuation) -> ModelCompletion:
    """Rebuild the suspended completion from the frozen join state."""

    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=child_wakeup.assistant_message,
            created_at=child_wakeup.tool_call.created_at,
            tool_calls=(child_wakeup.tool_call,),
        ),
        tool_calls=(child_wakeup.tool_call,),
    )


def child_wakeup_tool_result(child_wakeup: ChildWakeupContinuation) -> ToolResult:
    """Render the terminal child results as the delegated tool's real result."""

    any_success = any(
        result.status == "completed" for result in child_wakeup.child_results
    )
    payload = {
        "status": "completed" if any_success else "failed",
        "resume": "durable_wakeup",
        "results": [
            {
                "child_task_id": result.child_task_id,
                "status": result.status,
                "summary": result.summary,
            }
            for result in child_wakeup.child_results
        ],
    }
    return ToolResult(
        tool_call_id=child_wakeup.tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED if any_success else ToolCallStatus.FAILED,
        output=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        metadata={
            "child_task_id": child_wakeup.child_results[0].child_task_id,
            "subagent_status": (
                "completed" if any_success else "failed"
            ),
            "durable_delegation": True,
            "child_results": [
                {
                    "child_task_id": result.child_task_id,
                    "status": result.status,
                    "summary": result.summary,
                }
                for result in child_wakeup.child_results
            ],
        },
    )
