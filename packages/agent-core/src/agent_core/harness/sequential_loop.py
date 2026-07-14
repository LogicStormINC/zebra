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
from agent_core.harness.orchestration_events import model_response_event, policy_decision_payload
from agent_core.harness.policy_step import policy_stop_result
from agent_core.harness.selection import ToolCallSelectionStrategy
from agent_core.harness.tool_execution import execute_tool_call
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.tool_gateway import ToolGatewayPort

_DEFAULT_MODEL_CALL_LIMIT = 8
_DEFAULT_TOOL_CALL_LIMIT = 6


class SequentialToolLoop:
    def __init__(
        self,
        *,
        model_gateway: ModelGatewayPort,
        policy_engine: PolicyEnginePort,
        tool_gateway: ToolGatewayPort,
        model_step: HarnessModelStep,
        verifier: VerifierHook,
        tool_selector: ToolCallSelectionStrategy,
        synthesize_tool_results: bool,
    ) -> None:
        self._model_gateway = model_gateway
        self._policy_engine = policy_engine
        self._tool_gateway = tool_gateway
        self._model_step = model_step
        self._verifier = verifier
        self._tool_selector = tool_selector
        self._synthesize_tool_results = synthesize_tool_results

    def continue_approved(
        self,
        context: HarnessContext,
        *,
        completion: ModelCompletion,
        tool_call: ToolCall,
        conversation: tuple[SessionMessage, ...],
        model_calls_used: int,
        tool_calls_executed: int,
    ) -> HarnessAttemptResult:
        messages = list(conversation) or self._model_step.build_initial_messages(
            context.task,
            created_at=context.attempt.started_at,
        )
        fingerprints = {
            action_fingerprint(call) for message in messages for call in message.tool_calls
        }
        return self._execute_and_continue(
            context,
            messages=messages,
            completion=completion,
            tool_call=tool_call,
            emitted_events=[],
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            fingerprints=fingerprints,
            metadata={"approval_continuation": True},
            emit_execution_started=False,
        )

    def advance(
        self,
        context: HarnessContext,
        *,
        messages: list[SessionMessage],
        completion: ModelCompletion,
        emitted_events: list[HarnessEventDraft],
        model_calls_used: int,
        tool_calls_executed: int,
        fingerprints: set[str],
        metadata: dict[str, object],
    ) -> HarnessAttemptResult:
        if not completion.tool_calls:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.COMPLETED,
                summary=(
                    "model completed without tool calls"
                    if tool_calls_executed == 0
                    else "tool sequence completed with final answer"
                ),
                assistant_message=completion.assistant_message.content,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata=metadata,
            )
        selection = self._tool_selector.select(completion.tool_calls)
        tool_call = selection.tool_call
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.TOOL_CALL_PROPOSED,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": context.attempt.number,
                    "tool_name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "selection_summary": selection.summary,
                    "selection_metadata": selection.metadata,
                },
            )
        )
        metadata = {
            **metadata,
            "tool_selection_summary": selection.summary,
            "tool_selection_metadata": selection.metadata,
        }
        if action_fingerprint(tool_call) in fingerprints:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.FAILED,
                summary=f"repeated tool call blocked: {tool_call.name}",
                assistant_message=completion.assistant_message.content,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata={**metadata, "stop_reason": "repeated_tool_call"},
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
            return policy_stop_result(
                context,
                messages=messages,
                completion=completion,
                tool_call=tool_call,
                decision=decision,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                metadata=metadata,
            )
        return self._execute_and_continue(
            context,
            messages=messages,
            completion=completion,
            tool_call=tool_call,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            fingerprints=fingerprints,
            metadata=metadata,
        )

    def _execute_and_continue(
        self,
        context: HarnessContext,
        *,
        messages: list[SessionMessage],
        completion: ModelCompletion,
        tool_call: ToolCall,
        emitted_events: list[HarnessEventDraft],
        model_calls_used: int,
        tool_calls_executed: int,
        fingerprints: set[str],
        metadata: dict[str, object],
        emit_execution_started: bool = True,
    ) -> HarnessAttemptResult:
        execution = execute_tool_call(
            context,
            tool_call,
            tool_gateway=self._tool_gateway,
            verifier=self._verifier,
            emitted_events=emitted_events,
            emit_execution_started=emit_execution_started,
        )
        tool_calls_executed += 1
        fingerprints.add(action_fingerprint(tool_call))
        metadata = {**metadata, **execution.metadata}
        if execution.result.status is not ToolCallStatus.EXECUTED:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.FAILED,
                summary=f"tool call failed: {tool_call.name}",
                assistant_message=completion.assistant_message.content,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata=metadata,
            )
        if not self._synthesize_tool_results:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.COMPLETED,
                summary=f"tool call completed: {tool_call.name}",
                assistant_message=completion.assistant_message.content,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata=metadata,
            )
        self._model_step.append_tool_exchange(
            messages,
            completion=completion,
            tool_call=tool_call,
            tool_result=execution.result,
            created_at=context.attempt.started_at,
        )
        return self._request_next_completion(
            context,
            messages=messages,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            fingerprints=fingerprints,
            metadata=metadata,
            fallback_message=completion.assistant_message.content,
        )

    def _request_next_completion(
        self,
        context: HarnessContext,
        *,
        messages: list[SessionMessage],
        emitted_events: list[HarnessEventDraft],
        model_calls_used: int,
        tool_calls_executed: int,
        fingerprints: set[str],
        metadata: dict[str, object],
        fallback_message: str,
    ) -> HarnessAttemptResult:
        model_limit = context.task.max_model_calls or _DEFAULT_MODEL_CALL_LIMIT
        tool_limit = context.task.max_tool_calls or _DEFAULT_TOOL_CALL_LIMIT
        if model_calls_used >= model_limit:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="model call budget exhausted before final answer",
                assistant_message=fallback_message,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata={**metadata, "stop_reason": "model_call_budget_exhausted"},
            )
        allow_tools = tool_calls_executed < tool_limit and model_calls_used + 1 < model_limit
        if not allow_tools:
            self._model_step.append_final_answer_instruction(
                messages,
                created_at=context.attempt.started_at,
            )
        completion = self._model_step.request_completion(
            messages,
            self._model_gateway,
            allow_tools=allow_tools,
        )
        model_calls_used += 1
        emitted_events.append(
            model_response_event(
                completion,
                attempt_number=context.attempt.number,
                response_stage="tool_loop" if completion.tool_calls else "final",
            )
        )
        if completion.tool_calls and not allow_tools:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="model requested a tool after the tool boundary closed",
                assistant_message=completion.assistant_message.content,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata={**metadata, "stop_reason": "tool_boundary_closed"},
            )
        return self.advance(
            context,
            messages=messages,
            completion=completion,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            fingerprints=fingerprints,
            metadata=metadata,
        )
