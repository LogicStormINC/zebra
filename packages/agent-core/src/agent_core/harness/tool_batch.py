from collections.abc import Mapping

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.attempt_result import (
    action_fingerprint,
    build_attempt_result,
    update_batch_observation_progress,
)
from agent_core.harness.clarification_step import clarification_stop_result
from agent_core.harness.concurrent_batch import (
    DEFAULT_REPEAT_HARD_STOP_THRESHOLD,
    ConcurrentToolBatchExecutor,
    ToolBatchResult,
    selection_evidence,
)
from agent_core.harness.hooks import VerifierHook
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import HarnessAttemptOutcome, HarnessContext, HarnessEventDraft
from agent_core.harness.orchestration_events import policy_decision_payload
from agent_core.harness.plan_step import execute_plan_call
from agent_core.harness.policy_step import policy_stop_result
from agent_core.harness.selection import ToolCallSelection
from agent_core.harness.tool_execution import execute_tool_call, record_tool_result
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.tool_gateway import ToolGatewayPort


class ToolBatchExecutor:
    def __init__(
        self,
        *,
        policy_engine: PolicyEnginePort,
        tool_gateway: ToolGatewayPort,
        model_step: HarnessModelStep,
        verifier: VerifierHook,
        parallel_safe_tools: frozenset[str],
        parallel_batch_limits: Mapping[str, int] | None,
        max_parallel_tool_calls: int,
        repeat_hard_stop_threshold: int = DEFAULT_REPEAT_HARD_STOP_THRESHOLD,
    ) -> None:
        if repeat_hard_stop_threshold <= 0:
            raise ValueError("repeat_hard_stop_threshold must be positive")
        self._policy_engine = policy_engine
        self._tool_gateway = tool_gateway
        self._model_step = model_step
        self._verifier = verifier
        self._repeat_hard_stop_threshold = repeat_hard_stop_threshold
        self._concurrent = ConcurrentToolBatchExecutor(
            policy_engine=policy_engine,
            tool_gateway=tool_gateway,
            model_step=model_step,
            verifier=verifier,
            parallel_safe_tools=parallel_safe_tools,
            parallel_batch_limits=parallel_batch_limits,
            max_parallel_tool_calls=max_parallel_tool_calls,
            repeat_hard_stop_threshold=repeat_hard_stop_threshold,
        )

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
        tool_call_limit: int | None,
        fingerprints: set[str],
        metadata: dict[str, object],
        execute_all: bool,
        first_selection: ToolCallSelection | None = None,
        first_execution_started: bool = False,
    ) -> ToolBatchResult:
        if not tool_calls:
            raise ValueError("tool batch must not be empty")
        if (
            tool_call_limit is not None
            and tool_calls_executed + len(tool_calls) > tool_call_limit
        ):
            return self._terminal(
                outcome=HarnessAttemptOutcome.SUSPENDED,
                summary="tool call budget cannot fit the complete proposed batch",
                completion=completion,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                metadata={
                    **metadata,
                    "stop_reason": "tool_call_budget_exhausted",
                    "tool_call_limit": tool_call_limit,
                    "proposed_tool_call_count": len(tool_calls),
                    "remaining_tool_budget": tool_call_limit - tool_calls_executed,
                    "remaining_tool_call_count": len(tool_calls),
                },
            )
        clarification_calls = tuple(call for call in tool_calls if call.name == "agent.clarify")
        if clarification_calls and len(tool_calls) != 1:
            return self._terminal(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="agent.clarify must be the only tool call in a model response",
                completion=completion,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                metadata={**metadata, "stop_reason": "invalid_clarification_batch"},
            )
        if execute_all and _can_recover_repeated_reads(
            tool_calls,
            fingerprints=fingerprints,
            metadata=metadata,
        ):
            return self._recover_repeated_reads(
                context,
                messages=messages,
                tool_calls=tool_calls,
                emitted_events=emitted_events,
                tool_calls_executed=tool_calls_executed,
                metadata=metadata,
                first_selection=first_selection,
            )
        if self._concurrent.can_execute(
            tool_calls,
            execute_all=execute_all,
            first_execution_started=first_execution_started,
        ):
            return self._concurrent.execute(
                context,
                messages=messages,
                completion=completion,
                tool_calls=tool_calls,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                tool_call_limit=tool_call_limit,
                fingerprints=fingerprints,
                metadata=metadata,
                first_selection=first_selection,
            )
        batch_event_start = len(emitted_events)
        observations: list[tuple[ToolCall, ToolResult]] = []
        for index, tool_call in enumerate(tool_calls):
            approved_continuation = index == 0 and first_execution_started
            if not approved_continuation:
                selection_summary, selection_metadata = selection_evidence(
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
                            "tool_call_id": str(tool_call.tool_call_id),
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
                    loop_guard_counts = _loop_guard_counts(metadata)
                    fingerprint = action_fingerprint(tool_call)
                    loop_guard_counts[fingerprint] = loop_guard_counts.get(fingerprint, 0) + 1
                    metadata = {**metadata, "loop_guard_counts": loop_guard_counts}
                    if loop_guard_counts[fingerprint] >= self._repeat_hard_stop_threshold:
                        return self._terminal(
                            outcome=HarnessAttemptOutcome.FAILED,
                            summary=(
                                f"loop guard exhausted: {tool_call.name} repeated "
                                f"{loop_guard_counts[fingerprint]} times"
                            ),
                            completion=completion,
                            emitted_events=emitted_events,
                            model_calls_used=model_calls_used,
                            tool_calls_executed=tool_calls_executed,
                            metadata={
                                **metadata,
                                "stop_reason": "loop_guard_exhausted",
                                "loop_guard_tool_name": tool_call.name,
                                "loop_guard_repeat_count": loop_guard_counts[fingerprint],
                                "remaining_tool_call_count": len(tool_calls) - index,
                            },
                        )
                    result = ToolResult(
                        tool_call_id=tool_call.tool_call_id,
                        status=ToolCallStatus.FAILED,
                        output=(
                            "This tool call repeats a previous call with identical "
                            "arguments. It was not executed again. Change the "
                            "arguments or pick a different tool to make progress."
                        ),
                        metadata={
                            "reason": "repeated_tool_call",
                            "retryable": True,
                            "executed": False,
                            "repeat_count": loop_guard_counts[fingerprint],
                        },
                    )
                    execution = record_tool_result(
                        context,
                        tool_call,
                        result,
                        verifier=self._verifier,
                        emitted_events=emitted_events,
                    )
                    observations.append((tool_call, result))
                    self._model_step.append_tool_result(
                        messages,
                        tool_call=tool_call,
                        tool_result=result,
                        created_at=context.attempt.started_at,
                    )
                    metadata = {**metadata, **execution.metadata}
                    continue
                decision = self._policy_engine.evaluate_tool_call(tool_call)
                emitted_events.append(
                    HarnessEventDraft(
                        event_type=EventType.POLICY_DECISION_MADE,
                        actor=EventActor.POLICY,
                        payload=policy_decision_payload(
                            attempt_number=context.attempt.number,
                            tool_call=tool_call,
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
            if tool_call.name == "agent.clarify":
                try:
                    terminal = clarification_stop_result(
                        context,
                        messages=messages,
                        completion=completion,
                        tool_call=tool_call,
                        emitted_events=emitted_events,
                        model_calls_used=model_calls_used,
                        tool_calls_executed=tool_calls_executed,
                        metadata=metadata,
                    )
                except ValueError as exc:
                    return self._terminal(
                        outcome=HarnessAttemptOutcome.FAILED,
                        summary="invalid agent.clarify request",
                        completion=completion,
                        emitted_events=emitted_events,
                        model_calls_used=model_calls_used,
                        tool_calls_executed=tool_calls_executed,
                        metadata={
                            **metadata,
                            "stop_reason": "invalid_clarification_request",
                            "detail": str(exc),
                        },
                    )
                return ToolBatchResult(terminal, tool_calls_executed, metadata)
            try:
                execution = (
                    execute_plan_call(
                        context,
                        tool_call,
                        verifier=self._verifier,
                        emitted_events=emitted_events,
                    )
                    if tool_call.name == "agent.plan"
                    else execute_tool_call(
                        context,
                        tool_call,
                        tool_gateway=self._tool_gateway,
                        verifier=self._verifier,
                        emitted_events=emitted_events,
                        emit_execution_started=not (index == 0 and first_execution_started),
                    )
                )
            except ValueError as exc:
                return self._terminal(
                    outcome=HarnessAttemptOutcome.FAILED,
                    summary="invalid agent.plan request",
                    completion=completion,
                    emitted_events=emitted_events,
                    model_calls_used=model_calls_used,
                    tool_calls_executed=tool_calls_executed,
                    metadata={
                        **metadata,
                        "stop_reason": "invalid_plan_request",
                        "detail": str(exc),
                    },
                )
            tool_calls_executed += 1
            fingerprints.add(action_fingerprint(tool_call))
            observations.append((tool_call, execution.result))
            metadata = {**metadata, **execution.metadata}
            self._model_step.append_tool_result(
                messages,
                tool_call=tool_call,
                tool_result=execution.result,
                created_at=context.attempt.started_at,
            )
            if execution.result.status is not ToolCallStatus.EXECUTED:
                metadata = _accumulate_failure(metadata, tool_call.name)
                continue
            if not execute_all:
                metadata = update_batch_observation_progress(
                    metadata,
                    observations,
                    emitted_events[batch_event_start:],
                    threshold=self._repeat_hard_stop_threshold,
                )
                return self._terminal(
                    outcome=HarnessAttemptOutcome.COMPLETED,
                    summary=f"tool call completed: {tool_call.name}",
                    completion=completion,
                    emitted_events=emitted_events,
                    model_calls_used=model_calls_used,
                    tool_calls_executed=tool_calls_executed,
                    metadata=metadata,
                )
        return ToolBatchResult(
            None,
            tool_calls_executed,
            update_batch_observation_progress(
                metadata,
                observations,
                emitted_events[batch_event_start:],
                threshold=self._repeat_hard_stop_threshold,
            ),
        )

    def _recover_repeated_reads(
        self,
        context: HarnessContext,
        *,
        messages: list[SessionMessage],
        tool_calls: tuple[ToolCall, ...],
        emitted_events: list[HarnessEventDraft],
        tool_calls_executed: int,
        metadata: dict[str, object],
        first_selection: ToolCallSelection | None,
    ) -> ToolBatchResult:
        recovered_metadata = dict(metadata)
        batch_event_start = len(emitted_events)
        observations: list[tuple[ToolCall, ToolResult]] = []
        for index, tool_call in enumerate(tool_calls):
            summary, selection_metadata = selection_evidence(
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
                        "tool_call_id": str(tool_call.tool_call_id),
                        "arguments": tool_call.arguments,
                        "selection_summary": summary,
                        "selection_metadata": selection_metadata,
                    },
                )
            )
            result = ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output=(
                    "This exact read-only tool call already completed earlier in "
                    "this session. It was not executed again. Reuse the prior "
                    "evidence and continue without requesting this call again."
                ),
                metadata={
                    "reason": "repeated_tool_call",
                    "recoverable": True,
                    "executed": False,
                },
            )
            execution = record_tool_result(
                context,
                tool_call,
                result,
                verifier=self._verifier,
                emitted_events=emitted_events,
            )
            observations.append((tool_call, result))
            self._model_step.append_tool_result(
                messages,
                tool_call=tool_call,
                tool_result=result,
                created_at=context.attempt.started_at,
            )
            recovered_metadata = {**recovered_metadata, **execution.metadata}
        recovered_metadata = update_batch_observation_progress(
            recovered_metadata,
            observations,
            emitted_events[batch_event_start:],
            threshold=self._repeat_hard_stop_threshold,
        )
        return ToolBatchResult(
            None,
            tool_calls_executed,
            {**recovered_metadata, "repeated_read_recovery_count": 1},
        )

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


def _can_recover_repeated_reads(
    tool_calls: tuple[ToolCall, ...],
    *,
    fingerprints: set[str],
    metadata: Mapping[str, object],
) -> bool:
    recovery_count = metadata.get("repeated_read_recovery_count", 0)
    if recovery_count != 0:
        return False
    return all(
        tool_call.name in {"files.read", "sessions.search"}
        and action_fingerprint(tool_call) in fingerprints
        for tool_call in tool_calls
    )


def _loop_guard_counts(metadata: Mapping[str, object]) -> dict[str, int]:
    raw = metadata.get("loop_guard_counts")
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool)}
    return {}


def _accumulate_failure(
    metadata: dict[str, object], tool_name: str
) -> dict[str, object]:
    prior_failures = metadata.get("recoverable_tool_failure_count", 0)
    failure_count = (
        prior_failures + 1
        if isinstance(prior_failures, int) and not isinstance(prior_failures, bool)
        else 1
    )
    return {
        **metadata,
        "recoverable_tool_failure_count": failure_count,
        "last_failed_tool_name": tool_name,
    }
