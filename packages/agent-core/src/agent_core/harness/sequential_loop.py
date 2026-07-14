from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.attempt_result import action_fingerprint, build_attempt_result
from agent_core.harness.hooks import VerifierHook
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)
from agent_core.harness.orchestration_events import (
    context_compacted_event,
    model_response_event,
)
from agent_core.harness.selection import ToolCallSelectionStrategy
from agent_core.harness.tool_batch import ToolBatchExecutor
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
        parallel_safe_tools: frozenset[str],
        max_parallel_tool_calls: int,
    ) -> None:
        self._model_gateway = model_gateway
        self._model_step = model_step
        self._tool_selector = tool_selector
        self._synthesize_tool_results = synthesize_tool_results
        self._batch_executor = ToolBatchExecutor(
            policy_engine=policy_engine,
            tool_gateway=tool_gateway,
            model_step=model_step,
            verifier=verifier,
            parallel_safe_tools=parallel_safe_tools,
            max_parallel_tool_calls=max_parallel_tool_calls,
        )

    def continue_approved(
        self,
        context: HarnessContext,
        *,
        completion: ModelCompletion,
        tool_call: ToolCall,
        remaining_tool_calls: tuple[ToolCall, ...],
        conversation: tuple[SessionMessage, ...],
        model_calls_used: int,
        tool_calls_executed: int,
    ) -> HarnessAttemptResult:
        messages = list(conversation) or self._model_step.build_initial_messages(
            context.task,
            created_at=context.attempt.started_at,
        )
        calls = (tool_call, *remaining_tool_calls)
        if not conversation:
            self._model_step.append_tool_batch(
                messages,
                completion=completion,
                tool_calls=calls,
            )
        fingerprints = _executed_action_fingerprints(messages)
        emitted_events: list[HarnessEventDraft] = []
        batch = self._batch_executor.execute(
            context,
            messages=messages,
            completion=completion,
            tool_calls=calls,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            tool_call_limit=_tool_limit(context),
            fingerprints=fingerprints,
            metadata={"approval_continuation": True},
            execute_all=self._synthesize_tool_results,
            first_execution_started=True,
        )
        if batch.terminal_result is not None:
            return batch.terminal_result
        return self._request_next_completion(
            context,
            messages=messages,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=batch.tool_calls_executed,
            fingerprints=fingerprints,
            metadata=batch.metadata,
            fallback_message=completion.assistant_message.content,
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
        calls = completion.tool_calls if self._synthesize_tool_results else (selection.tool_call,)
        self._model_step.append_tool_batch(
            messages,
            completion=completion,
            tool_calls=calls,
        )
        batch = self._batch_executor.execute(
            context,
            messages=messages,
            completion=completion,
            tool_calls=calls,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            tool_call_limit=_tool_limit(context),
            fingerprints=fingerprints,
            metadata=metadata,
            execute_all=self._synthesize_tool_results,
            first_selection=(selection if selection.tool_call == calls[0] else None),
        )
        if batch.terminal_result is not None:
            return batch.terminal_result
        return self._request_next_completion(
            context,
            messages=messages,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=batch.tool_calls_executed,
            fingerprints=fingerprints,
            metadata=batch.metadata,
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
        allow_tools = (
            tool_calls_executed < _tool_limit(context) and model_calls_used + 1 < model_limit
        )
        if not allow_tools:
            self._model_step.append_final_answer_instruction(
                messages,
                created_at=context.attempt.started_at,
            )
        compaction = self._model_step.compact_conversation(
            messages,
            user_goal=context.task.user_input,
            created_at=context.attempt.started_at,
        )
        if compaction is not None and compaction.compacted:
            messages[:] = compaction.messages
            emitted_events.append(
                context_compacted_event(
                    compaction,
                    attempt_number=context.attempt.number,
                )
            )
            previous_count = metadata.get("conversation_compaction_count", 0)
            compaction_count = (
                previous_count
                if isinstance(previous_count, int) and not isinstance(previous_count, bool)
                else 0
            )
            metadata = {
                **metadata,
                "conversation_compaction_count": compaction_count + 1,
                "conversation_tokens_after_compaction": compaction.after_tokens,
            }
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


def _executed_action_fingerprints(messages: list[SessionMessage]) -> set[str]:
    completed_ids = {
        message.tool_call_id for message in messages if message.role is MessageRole.TOOL
    }
    return {
        action_fingerprint(call)
        for message in messages
        for call in message.tool_calls
        if (call.provider_call_id or str(call.tool_call_id)) in completed_ids
    }


def _tool_limit(context: HarnessContext) -> int:
    return context.task.max_tool_calls or _DEFAULT_TOOL_CALL_LIMIT
