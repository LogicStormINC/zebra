from dataclasses import dataclass

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.harness.attempt_result import action_fingerprint, build_attempt_result
from agent_core.harness.hooks import VerifierHook
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)
from agent_core.harness.orchestration_events import policy_decision_payload
from agent_core.harness.policy_step import policy_stop_result
from agent_core.harness.selection import ToolCallSelection
from agent_core.harness.tool_execution import execute_tool_call
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.tool_gateway import ToolGatewayPort


@dataclass(frozen=True)
class ToolBatchResult:
    terminal_result: HarnessAttemptResult | None
    tool_calls_executed: int
    metadata: dict[str, object]


class ToolBatchExecutor:
    def __init__(
        self,
        *,
        policy_engine: PolicyEnginePort,
        tool_gateway: ToolGatewayPort,
        model_step: HarnessModelStep,
        verifier: VerifierHook,
    ) -> None:
        self._policy_engine = policy_engine
        self._tool_gateway = tool_gateway
        self._model_step = model_step
        self._verifier = verifier

    def execute(
        self,
        context: HarnessContext,
        *,
        messages: list[SessionMessage],
        completion: ModelCompletion,
        tool_calls: tuple[ToolCall, ...],
        emitted_events: list[HarnessEventDraft],
        model_calls_used: int,
        tool_calls_executed: int,
        tool_call_limit: int,
        fingerprints: set[str],
        metadata: dict[str, object],
        execute_all: bool,
        first_selection: ToolCallSelection | None = None,
        first_execution_started: bool = False,
    ) -> ToolBatchResult:
        if not tool_calls:
            raise ValueError("tool batch must not be empty")
        for index, tool_call in enumerate(tool_calls):
            if tool_calls_executed >= tool_call_limit:
                return self._terminal(
                    outcome=HarnessAttemptOutcome.FAILED,
                    summary="tool call budget exhausted before batch completed",
                    completion=completion,
                    emitted_events=emitted_events,
                    model_calls_used=model_calls_used,
                    tool_calls_executed=tool_calls_executed,
                    metadata={
                        **metadata,
                        "stop_reason": "tool_call_budget_exhausted",
                        "remaining_tool_call_count": len(tool_calls) - index,
                    },
                )
            approved_continuation = index == 0 and first_execution_started
            if not approved_continuation:
                selection_summary, selection_metadata = _selection_evidence(
                    index=index,
                    count=len(tool_calls),
                    first_selection=first_selection,
                )
                emitted_events.append(
                    HarnessEventDraft(
                        event_type=EventType.TOOL_CALL_PROPOSED,
                        actor=EventActor.HARNESS,
                        payload={
                            "attempt_number": context.attempt.number,
                            "tool_name": tool_call.name,
                            "arguments": tool_call.arguments,
                            "selection_summary": selection_summary,
                            "selection_metadata": selection_metadata,
                        },
                    )
                )
                metadata = {
                    **metadata,
                    "tool_selection_summary": selection_summary,
                    "tool_selection_metadata": selection_metadata,
                }
                if action_fingerprint(tool_call) in fingerprints:
                    return self._terminal(
                        outcome=HarnessAttemptOutcome.FAILED,
                        summary=f"repeated tool call blocked: {tool_call.name}",
                        completion=completion,
                        emitted_events=emitted_events,
                        model_calls_used=model_calls_used,
                        tool_calls_executed=tool_calls_executed,
                        metadata={
                            **metadata,
                            "stop_reason": "repeated_tool_call",
                            "remaining_tool_call_count": len(tool_calls) - index,
                        },
                    )
                decision = self._policy_engine.evaluate_tool_call(tool_call)
                emitted_events.append(
                    HarnessEventDraft(
                        event_type=EventType.POLICY_DECISION_MADE,
                        actor=EventActor.POLICY,
                        payload=policy_decision_payload(
                            attempt_number=context.attempt.number,
                            tool_name=tool_call.name,
                            decision=decision,
                        ),
                    )
                )
                if decision.decision is not PolicyDecisionType.ALLOW:
                    terminal = policy_stop_result(
                        context,
                        messages=messages,
                        completion=completion,
                        tool_call=tool_call,
                        decision=decision,
                        emitted_events=emitted_events,
                        model_calls_used=model_calls_used,
                        tool_calls_executed=tool_calls_executed,
                        metadata=metadata,
                        remaining_tool_calls=tool_calls[index + 1 :],
                    )
                    return ToolBatchResult(terminal, tool_calls_executed, metadata)
            execution = execute_tool_call(
                context,
                tool_call,
                tool_gateway=self._tool_gateway,
                verifier=self._verifier,
                emitted_events=emitted_events,
                emit_execution_started=not (index == 0 and first_execution_started),
            )
            tool_calls_executed += 1
            fingerprints.add(action_fingerprint(tool_call))
            metadata = {**metadata, **execution.metadata}
            self._model_step.append_tool_result(
                messages,
                tool_call=tool_call,
                tool_result=execution.result,
                created_at=context.attempt.started_at,
            )
            if execution.result.status is not ToolCallStatus.EXECUTED:
                return self._terminal(
                    outcome=HarnessAttemptOutcome.FAILED,
                    summary=f"tool call failed: {tool_call.name}",
                    completion=completion,
                    emitted_events=emitted_events,
                    model_calls_used=model_calls_used,
                    tool_calls_executed=tool_calls_executed,
                    metadata={
                        **metadata,
                        "remaining_tool_call_count": len(tool_calls) - index - 1,
                    },
                )
            if not execute_all:
                return self._terminal(
                    outcome=HarnessAttemptOutcome.COMPLETED,
                    summary=f"tool call completed: {tool_call.name}",
                    completion=completion,
                    emitted_events=emitted_events,
                    model_calls_used=model_calls_used,
                    tool_calls_executed=tool_calls_executed,
                    metadata=metadata,
                )
        return ToolBatchResult(None, tool_calls_executed, metadata)

    @staticmethod
    def _terminal(
        *,
        outcome: HarnessAttemptOutcome,
        summary: str,
        completion: ModelCompletion,
        emitted_events: list[HarnessEventDraft],
        model_calls_used: int,
        tool_calls_executed: int,
        metadata: dict[str, object],
    ) -> ToolBatchResult:
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


def _selection_evidence(
    *,
    index: int,
    count: int,
    first_selection: ToolCallSelection | None,
) -> tuple[str, dict[str, object]]:
    if index == 0 and first_selection is not None:
        return first_selection.summary, first_selection.metadata
    return (
        "selected provider-order tool call",
        {"selected_index": index, "candidate_count": count},
    )
