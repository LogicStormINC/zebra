from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.hooks import VerifierHook
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)
from agent_core.harness.orchestration_events import approval_requested_payload
from agent_core.harness.tool_execution import ToolExecutionStep, record_tool_result


def policy_stop_result(
    context: HarnessContext,
    *,
    messages: list[SessionMessage],
    completion: ModelCompletion,
    tool_call: ToolCall,
    decision: PolicyDecision,
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
    remaining_tool_calls: tuple[ToolCall, ...] = (),
) -> HarnessAttemptResult:
    waiting = decision.decision is PolicyDecisionType.REQUIRE_APPROVAL
    if waiting:
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.APPROVAL_REQUESTED,
                actor=EventActor.POLICY,
                payload=approval_requested_payload(
                    attempt_number=context.attempt.number,
                    tool_call=tool_call,
                    assistant_message=completion.assistant_message.content,
                    decision=decision,
                    conversation=messages,
                    model_calls_used=model_calls_used,
                    tool_calls_executed=tool_calls_executed,
                    remaining_tool_calls=remaining_tool_calls,
                ),
            )
        )
    return build_attempt_result(
        outcome=(
            HarnessAttemptOutcome.WAITING_APPROVAL if waiting else HarnessAttemptOutcome.FAILED
        ),
        summary=("tool call requires approval" if waiting else "tool call blocked by policy"),
        assistant_message=completion.assistant_message.content,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        emitted_events=emitted_events,
        metadata={
            **metadata,
            "tool_name": tool_call.name,
            "policy_decision": decision.decision.value,
        },
    )


def recoverable_policy_deny_observation(
    context: HarnessContext,
    *,
    messages: list[SessionMessage],
    tool_call: ToolCall,
    decision: PolicyDecision,
    retained_tool_calls: tuple[ToolCall, ...],
    model_step: HarnessModelStep,
    verifier: VerifierHook,
    emitted_events: list[HarnessEventDraft],
) -> ToolExecutionStep:
    if decision.decision is not PolicyDecisionType.DENY or not decision.recoverable:
        raise ValueError("policy decision is not a recoverable deny")
    _retain_tool_call_batch(messages, tool_call, retained_tool_calls)
    result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        output=decision.reason,
        metadata={"reason": decision.reason, "executed": False},
    )
    execution = record_tool_result(
        context,
        tool_call,
        result,
        verifier=verifier,
        emitted_events=emitted_events,
    )
    model_step.append_tool_result(
        messages,
        tool_call=tool_call,
        tool_result=result,
        created_at=context.attempt.started_at,
    )
    return execution


def policy_recovery_metadata(metadata: dict[str, object]) -> dict[str, object]:
    prior = metadata.get("recoverable_policy_deny_count")
    count = prior + 1 if isinstance(prior, int) and not isinstance(prior, bool) else 1
    return {
        **metadata,
        "recoverable_policy_deny_count": count,
        "policy_recovery_terminal_synthesis": count >= 2,
    }


def _retain_tool_call_batch(
    messages: list[SessionMessage],
    tool_call: ToolCall,
    retained_tool_calls: tuple[ToolCall, ...],
) -> None:
    if not retained_tool_calls or tool_call not in retained_tool_calls:
        raise ValueError("retained tool batch must contain the denied tool call")
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if any(call.tool_call_id == tool_call.tool_call_id for call in message.tool_calls):
            messages[index] = message.model_copy(update={"tool_calls": retained_tool_calls})
            return
    raise ValueError("denied tool call is missing from the model conversation")
