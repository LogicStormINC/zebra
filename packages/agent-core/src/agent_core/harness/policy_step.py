from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)
from agent_core.harness.orchestration_events import approval_requested_payload


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
