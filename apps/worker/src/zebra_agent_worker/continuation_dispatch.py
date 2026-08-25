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
from zebra_agent_worker.client_effect_resume import (
    ClientEffectWakeup,
    client_effect_wakeup_completion,
    client_effect_wakeup_tool_result,
)

if TYPE_CHECKING:
    from agent_core.harness.orchestrator import SingleAttemptOrchestrator


def run_continuation(
    orchestrator: SingleAttemptOrchestrator,
    context: HarnessContext,
    *,
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
    child_wakeup: ChildWakeupContinuation | None = None,
    client_effect: ClientEffectWakeup | None = None,
) -> HarnessAttemptResult:
    if client_effect is not None:
        return orchestrator.continue_completed_tool(
            context,
            completion=client_effect_wakeup_completion(client_effect),
            tool_call=client_effect.tool_call,
            tool_result=client_effect_wakeup_tool_result(client_effect),
            conversation=client_effect.conversation,
            model_calls_used=client_effect.model_calls_used,
            tool_calls_executed=client_effect.tool_calls_executed,
            assistant_message=client_effect.assistant_message,
        )
    if child_wakeup is not None:
        return orchestrator.continue_completed_tools(
            context,
            completion=child_wakeup_completion(child_wakeup),
            tool_calls=child_wakeup.tool_calls,
            tool_results=child_wakeup_tool_results(child_wakeup),
            conversation=child_wakeup.conversation,
            model_calls_used=child_wakeup.model_calls_used,
            tool_calls_executed=child_wakeup.tool_calls_executed,
            assistant_message=child_wakeup.assistant_message,
            metadata={"child_wakeup_continuation": True},
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
            tool_calls=child_wakeup.tool_calls,
        ),
        tool_calls=child_wakeup.tool_calls,
    )


def child_wakeup_tool_results(child_wakeup: ChildWakeupContinuation) -> tuple[ToolResult, ...]:
    """Render each delegated call's terminal child result as its real result.

    ``tool_calls`` and ``child_results`` are aligned by the recovery: the
    i-th result belongs to the i-th delegated call.
    """

    results: list[ToolResult] = []
    for tool_call, delivery in zip(
        child_wakeup.tool_calls, child_wakeup.child_results, strict=True
    ):
        executed = delivery.status == "completed"
        payload = {
            "status": delivery.status,
            "resume": "durable_wakeup",
            "child_task_id": delivery.child_task_id,
            "summary": delivery.summary,
        }
        results.append(
            ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.EXECUTED if executed else ToolCallStatus.FAILED,
                output=json.dumps(payload, separators=(",", ":"), sort_keys=True),
                metadata={
                    "child_task_id": delivery.child_task_id,
                    "subagent_status": delivery.status,
                    "durable_delegation": True,
                    "summary": delivery.summary,
                },
            )
        )
    return tuple(results)
