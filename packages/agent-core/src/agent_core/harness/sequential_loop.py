from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME,
    ModelCompletion,
)
from agent_core.domain.events import EventType
from agent_core.domain.tools import ToolCall
from agent_core.harness import context_recovery
from agent_core.harness.attempt_result import (
    action_fingerprint,
    append_no_progress_observation,
    build_attempt_result,
)
from agent_core.harness.clarification_step import clarification_tool_result
from agent_core.harness.completion_evidence import (
    complete_without_tools,
    continue_after_tool_batch,
    prepare_terminal_synthesis_evidence,
    should_use_provisional_final,
    terminal_synthesis_completion_evidence,
)
from agent_core.harness.hooks import VerifierHook
from agent_core.harness.model_request import allowed_response_repairs
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventBuffer,
    HarnessEventDraft,
)
from agent_core.harness.orchestration_events import model_response_event
from agent_core.harness.selection import ToolCallSelectionStrategy
from agent_core.harness.tool_batch import ToolBatchExecutor
from agent_core.harness.tool_resolution import (
    ToolCallResolver,
    resolve_completion_tool_calls,
)
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.tool_gateway import ToolGatewayPort


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
        parallel_batch_limits: Mapping[str, int] | None,
        max_parallel_tool_calls: int,
        tool_call_resolver: ToolCallResolver | None,
        validator_tool_names: frozenset[str],
        event_sink: Callable[[HarnessEventDraft], None] | None = None,
    ) -> None:
        self._model_gateway = model_gateway
        self._model_step = model_step
        self._tool_selector = tool_selector
        self._synthesize_tool_results = synthesize_tool_results
        self._tool_call_resolver = tool_call_resolver
        self._event_sink = event_sink
        self._batch_executor = ToolBatchExecutor(
            policy_engine=policy_engine,
            tool_gateway=tool_gateway,
            model_step=model_step,
            verifier=verifier,
            parallel_safe_tools=parallel_safe_tools,
            parallel_batch_limits=parallel_batch_limits,
            max_parallel_tool_calls=max_parallel_tool_calls,
            validator_tool_names=validator_tool_names,
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
            model_gateway=self._model_gateway,
        )
        calls = (tool_call, *remaining_tool_calls)
        if not conversation:
            self._model_step.append_tool_batch(
                messages,
                completion=completion,
                tool_calls=calls,
            )
        fingerprints = _executed_action_fingerprints(
            messages, since=context.attempt.started_at
        )
        emitted_events: list[HarnessEventDraft] = HarnessEventBuffer(self._event_sink)
        batch = self._batch_executor.execute(
            context,
            messages=messages,
            completion=completion,
            tool_calls=calls,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            tool_call_limit=context.task.max_tool_calls,
            fingerprints=fingerprints,
            metadata={"approval_continuation": True},
            execute_all=self._synthesize_tool_results,
            first_execution_started=True,
        )
        return continue_after_tool_batch(
            context,
            messages=messages,
            completion=completion,
            emitted_events=emitted_events,
            fingerprints=fingerprints,
            batch=batch,
            model_calls_used=model_calls_used,
            request_terminal_synthesis=self._request_terminal_synthesis,
            request_next_completion=self._request_next_completion,
        )

    def continue_clarification(
        self,
        context: HarnessContext,
        *,
        tool_call: ToolCall,
        response: str,
        conversation: tuple[SessionMessage, ...],
        model_calls_used: int,
        tool_calls_executed: int,
        assistant_message: str,
    ) -> HarnessAttemptResult:
        messages = list(conversation)
        clarification_id = str(tool_call.tool_call_id)
        result = clarification_tool_result(
            tool_call.tool_call_id,
            clarification_id,
            response,
        )
        self._model_step.append_tool_result(
            messages,
            tool_call=tool_call,
            tool_result=result,
            created_at=context.attempt.started_at,
        )
        return self._request_next_completion(
            context,
            messages=messages,
            emitted_events=HarnessEventBuffer(self._event_sink),
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            fingerprints=_executed_action_fingerprints(
                messages, since=context.attempt.started_at
            ),
            metadata={
                "clarification_continuation": True,
                "clarification_id": clarification_id,
            },
            fallback_message=assistant_message,
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
        try:
            completion = resolve_completion_tool_calls(
                completion,
                self._tool_call_resolver,
            )
        except ValueError as exc:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="invalid progressive tool disclosure call",
                assistant_message=completion.assistant_message.content,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata={
                    **metadata,
                    "stop_reason": "invalid_tool_bridge",
                    "detail": str(exc),
                },
        )
        if not completion.tool_calls:
            contract = _final_output_contract(emitted_events, completion)
            _bind_final_output_contract(emitted_events, contract)
            if contract is not None:
                metadata = {**metadata, "output_contract": contract}
            return complete_without_tools(
                context,
                messages=messages,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                metadata=metadata,
                assistant_message=completion.assistant_message.content,
                fingerprints=fingerprints,
                request_next_completion=self._request_next_completion,
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
            tool_call_limit=context.task.max_tool_calls,
            fingerprints=fingerprints,
            metadata=metadata,
            execute_all=self._synthesize_tool_results,
            first_selection=(selection if selection.tool_call == calls[0] else None),
        )
        return continue_after_tool_batch(
            context,
            messages=messages,
            completion=completion,
            emitted_events=emitted_events,
            fingerprints=fingerprints,
            batch=batch,
            model_calls_used=model_calls_used,
            request_terminal_synthesis=self._request_terminal_synthesis,
            request_next_completion=self._request_next_completion,
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
        model_limit = context.task.max_model_calls
        if model_limit is not None and model_calls_used >= model_limit:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.SUSPENDED,
                summary="model call budget reached; execution can continue with a larger budget",
                assistant_message=fallback_message,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata={**metadata, "stop_reason": "model_call_budget_exhausted"},
            )
        tool_limit = context.task.max_tool_calls
        tool_budget_open = tool_limit is None or tool_calls_executed < tool_limit
        model_budget_allows_followup = (
            model_limit is None or model_calls_used + 1 < model_limit
        )
        allow_tools = tool_budget_open and model_budget_allows_followup
        compaction = (
            self._model_step.prepare_conversation(
                messages,
                self._model_gateway,
                allow_tools=True,
                user_goal=context.task.user_input,
                created_at=context.attempt.started_at,
                **(
                    {"media_inputs": context.task.media_inputs}
                    if context.task.media_inputs
                    else {}
                ),
            )
            if allow_tools
            else context_recovery.prepare_terminal_conversation(
                messages,
                self._model_gateway,
                self._model_step,
                context.task.user_input,
                context.attempt.started_at,
                **(
                    {"media_inputs": context.task.media_inputs}
                    if context.task.media_inputs
                    else {}
                ),
            )
        )
        metadata = context_recovery.record_compaction(
            compaction,
            model_step=self._model_step,
            model_gateway=self._model_gateway,
            context=context,
            emitted_events=emitted_events,
            metadata=metadata,
        )
        completion = self._model_step.request_completion(
            messages,
            self._model_gateway,
            allow_tools=allow_tools,
            media_inputs=context.task.media_inputs,
            response_repair_limit=allowed_response_repairs(
                model_limit,
                model_calls_used,
            ),
        )
        model_calls_used += 1 + completion.call_metadata.response_repair_count
        compaction_count = metadata.get("conversation_compaction_count")
        provisional_final = should_use_provisional_final(
            context,
            emitted_events,
            allow_tools=allow_tools,
            has_tool_calls=bool(completion.tool_calls),
            tool_calls_executed=tool_calls_executed,
            compaction_happened=compaction is not None and compaction.compacted,
            compaction_count=compaction_count,
        )
        response_stage = (
            "tool_loop" if completion.tool_calls or provisional_final else "final"
        )
        # The event sink persists each draft at append time, so the final
        # event must already carry the emit-tool contract BEFORE it is
        # appended; a later in-buffer replace would never reach the store.
        contract = (
            _final_output_contract(emitted_events, completion)
            if response_stage == "final"
            else None
        )
        emitted_events.append(
            model_response_event(
                completion,
                attempt_number=context.attempt.number,
                response_stage=response_stage,
                output_contract=contract,
            )
        )
        if provisional_final:
            return self._request_terminal_synthesis(
                context,
                messages=messages,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                metadata=metadata,
                fallback_message=completion.assistant_message.content,
                include_no_progress_observation=False,
            )
        if completion.tool_calls and not allow_tools:
            stop_reason = (
                "tool_call_budget_exhausted"
                if not tool_budget_open
                else "model_call_budget_exhausted"
            )
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.SUSPENDED,
                summary="explicit call budget reached; execution can continue with a larger budget",
                assistant_message=completion.assistant_message.content,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata={**metadata, "stop_reason": stop_reason},
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

    def _request_terminal_synthesis(
        self,
        context: HarnessContext,
        *,
        messages: list[SessionMessage],
        emitted_events: list[HarnessEventDraft],
        model_calls_used: int,
        tool_calls_executed: int,
        metadata: dict[str, object],
        fallback_message: str,
        include_no_progress_observation: bool = True,
    ) -> HarnessAttemptResult:
        model_limit = context.task.max_model_calls
        if model_limit is not None and model_calls_used >= model_limit:
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.SUSPENDED,
                summary="model call budget reached before tool-loop final synthesis",
                assistant_message=fallback_message,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata={**metadata, "stop_reason": "model_call_budget_exhausted"},
            )
        evidence_result = prepare_terminal_synthesis_evidence(
            context,
            messages=messages,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            metadata=metadata,
            fallback_message=fallback_message,
            fingerprints=_executed_action_fingerprints(
                messages, since=context.attempt.started_at
            ),
            request_next_completion=self._request_next_completion,
        )
        if evidence_result is not None:
            return evidence_result
        metadata = {**metadata, "terminal_synthesis_attempted": True}
        if metadata.get("validator_correction_required") is True:
            metadata = {**metadata, "validator_correction_attempted": True}
            context_recovery.append_validator_correction_instruction(
                messages,
                created_at=context.attempt.started_at,
            )
        if include_no_progress_observation:
            append_no_progress_observation(
                messages,
                metadata=metadata,
                created_at=context.attempt.started_at,
            )
        compaction = context_recovery.prepare_terminal_conversation(
            messages,
            self._model_gateway,
            self._model_step,
            context.task.user_input,
            context.attempt.started_at,
            **(
                {"media_inputs": context.task.media_inputs}
                if context.task.media_inputs
                else {}
            ),
        )
        metadata = context_recovery.record_compaction(
            compaction,
            model_step=self._model_step,
            model_gateway=self._model_gateway,
            context=context,
            emitted_events=emitted_events,
            metadata=metadata,
        )
        completion = self._model_step.request_completion(
            messages,
            self._model_gateway,
            allow_tools=False,
            media_inputs=context.task.media_inputs,
            response_repair_limit=allowed_response_repairs(model_limit, model_calls_used),
        )
        model_calls_used += 1 + completion.call_metadata.response_repair_count
        contract = _final_output_contract(emitted_events, completion)
        # Same sink constraint as above: inject the contract before append.
        emitted_events.append(
            model_response_event(
                completion,
                attempt_number=context.attempt.number,
                response_stage="final",
                output_contract=contract,
            )
        )
        _bind_final_output_contract(emitted_events, contract)
        if contract is not None:
            metadata = {**metadata, "output_contract": contract}
        if (
            completion.tool_calls
            or _is_raw_dsml_tool_request(completion.assistant_message.content)
            or not completion.assistant_message.content.strip()
        ):
            return build_attempt_result(
                outcome=HarnessAttemptOutcome.SUSPENDED,
                summary="tool loop made no new progress and final synthesis was unavailable",
                assistant_message=completion.assistant_message.content,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                emitted_events=emitted_events,
                metadata={**metadata, "stop_reason": "tool_loop_no_progress"},
            )
        evidence_result = terminal_synthesis_completion_evidence(
            context,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            metadata=metadata,
            assistant_message=completion.assistant_message.content,
        )
        if evidence_result is not None:
            return evidence_result
        return build_attempt_result(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="tool loop converged with a final answer",
            assistant_message=completion.assistant_message.content,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            emitted_events=emitted_events,
            metadata=metadata,
        )


def _executed_action_fingerprints(
    messages: list[SessionMessage],
    *,
    since: datetime | None = None,
) -> set[str]:
    completed_ids = {
        message.tool_call_id for message in messages if message.role is MessageRole.TOOL
    }
    return {
        action_fingerprint(call)
        for message in messages
        if since is None or message.created_at >= since
        for call in message.tool_calls
        if (call.provider_call_id or str(call.tool_call_id)) in completed_ids
    }


def _final_output_contract(
    emitted_events: list[HarnessEventDraft],
    completion: ModelCompletion,
) -> dict[str, object] | None:
    """The output_contract strictly bound to the FINAL answer.

    Only the dedicated producer tool (``artifact.output_contract.emit``) may
    contribute a contract through tool-result metadata; ANY other tool's
    ``output_contract`` metadata is ignored, so a forged envelope from a
    local, MCP or business-provider tool can never become the Artifact
    contract source. The last legal emission in the terminal attempt wins;
    otherwise the final completion's own gateway channel
    (``ModelCompletion.output_contract``) applies. Contracts from earlier
    tool-loop rounds never leak into the final metadata because only the
    terminal sites bind and non-final events never carry one.
    """
    emitted: dict[str, object] | None = None
    for event in emitted_events:
        if event.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
            continue
        if event.payload.get("tool_name") != ARTIFACT_OUTPUT_CONTRACT_EMIT_TOOL_NAME:
            continue
        metadata = event.payload.get("metadata")
        candidate = (
            metadata.get("output_contract")
            if isinstance(metadata, Mapping)
            else None
        )
        if isinstance(candidate, Mapping):
            emitted = dict(candidate)
    if emitted is not None:
        return emitted
    if completion.output_contract is not None:
        return dict(completion.output_contract)
    return None


def _bind_final_output_contract(
    emitted_events: list[HarnessEventDraft],
    contract: dict[str, object] | None,
) -> None:
    """Attach the contract to the final MODEL_RESPONSE_RECEIVED event only."""
    if contract is None:
        return
    for index in range(len(emitted_events) - 1, -1, -1):
        event = emitted_events[index]
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
            emitted_events[index] = replace(
                event,
                payload={
                    **event.payload,
                    "output_contract": dict(contract),
                },
            )
            break


def _is_raw_dsml_tool_request(content: str) -> bool:
    marker = "<｜｜DSML｜｜tool_calls>"
    marker_index = 0
    while True:
        marker_index = content.find(marker, marker_index)
        if marker_index < 0:
            return False
        invoke_index = content.find("invoke name=", marker_index + len(marker))
        if (
            not _is_inside_fenced_code_block(content, marker_index)
            and invoke_index >= 0
            and not _is_inside_fenced_code_block(content, invoke_index)
        ):
            return True
        marker_index += len(marker)


def _is_inside_fenced_code_block(content: str, position: int) -> bool:
    return sum(line.lstrip().startswith("```") for line in content[:position].splitlines()) % 2 == 1
