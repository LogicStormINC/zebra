from agent_core.domain.events import EventActor, EventType
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCallStatus
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.tool_gateway import ToolGatewayPort


class SingleAttemptOrchestrator:
    def __init__(
        self,
        model_gateway: ModelGatewayPort,
        policy_engine: PolicyEnginePort,
        tool_gateway: ToolGatewayPort,
        *,
        model_step: HarnessModelStep | None = None,
    ) -> None:
        self._model_gateway = model_gateway
        self._policy_engine = policy_engine
        self._tool_gateway = tool_gateway
        self._model_step = model_step or HarnessModelStep()

    def run(self, context: HarnessContext) -> HarnessAttemptResult:
        completion = self._model_step.request_initial_completion(
            context.task,
            self._model_gateway,
            created_at=context.attempt.started_at,
        )
        emitted_events = [
            HarnessEventDraft(
                event_type=EventType.MODEL_RESPONSE_RECEIVED,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": context.attempt.number,
                    "assistant_message": completion.assistant_message.content,
                    "tool_call_count": len(completion.tool_calls),
                },
            )
        ]

        if not completion.tool_calls:
            return HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.COMPLETED,
                summary="model completed without tool calls",
                metadata={
                    "assistant_message": completion.assistant_message.content,
                    "tool_call_count": 0,
                },
                emitted_events=tuple(emitted_events),
            )

        tool_call = completion.tool_calls[0]
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.TOOL_CALL_PROPOSED,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": context.attempt.number,
                    "tool_name": tool_call.name,
                    "arguments": tool_call.arguments,
                },
            )
        )

        decision = self._policy_engine.evaluate_tool_call(tool_call)
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.POLICY_DECISION_MADE,
                actor=EventActor.POLICY,
                payload={
                    "attempt_number": context.attempt.number,
                    "decision": decision.decision.value,
                    "reason": decision.reason,
                    "policy_profile": decision.policy_profile,
                    "tool_name": tool_call.name,
                },
            )
        )
        if decision.decision is not PolicyDecisionType.ALLOW:
            return HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="tool call blocked by policy",
                metadata={
                    "assistant_message": completion.assistant_message.content,
                    "tool_name": tool_call.name,
                    "policy_decision": decision.decision.value,
                },
                emitted_events=tuple(emitted_events),
            )

        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.TOOL_EXECUTION_STARTED,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": context.attempt.number,
                    "tool_name": tool_call.name,
                },
            )
        )
        tool_result = self._tool_gateway.execute(tool_call)
        emitted_events.append(
            HarnessEventDraft(
                event_type=(
                    EventType.TOOL_EXECUTION_COMPLETED
                    if tool_result.status is ToolCallStatus.EXECUTED
                    else EventType.TOOL_EXECUTION_FAILED
                ),
                actor=EventActor.TOOL,
                payload={
                    "attempt_number": context.attempt.number,
                    "tool_name": tool_call.name,
                    "status": tool_result.status.value,
                    "output": tool_result.output,
                    "metadata": tool_result.metadata,
                },
            )
        )
        return HarnessAttemptResult(
            outcome=(
                HarnessAttemptOutcome.COMPLETED
                if tool_result.status is ToolCallStatus.EXECUTED
                else HarnessAttemptOutcome.FAILED
            ),
            summary=(
                f"tool call completed: {tool_call.name}"
                if tool_result.status is ToolCallStatus.EXECUTED
                else f"tool call failed: {tool_call.name}"
            ),
            metadata={
                "assistant_message": completion.assistant_message.content,
                "tool_name": tool_call.name,
                "tool_status": tool_result.status.value,
                "tool_output": tool_result.output,
                "tool_metadata": tool_result.metadata,
            },
            emitted_events=tuple(emitted_events),
        )
