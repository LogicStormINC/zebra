from collections import Counter
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

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
from agent_core.harness.hooks import VerifierHook
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)
from agent_core.harness.orchestration_events import policy_decision_payload
from agent_core.harness.policy_step import (
    policy_recovery_metadata,
    policy_stop_result,
    recoverable_policy_deny_observation,
)
from agent_core.harness.selection import ToolCallSelection
from agent_core.harness.subagent_metadata import aggregate_subagent_metadata
from agent_core.harness.tool_execution import record_tool_result
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.tool_gateway import ToolGatewayPort

DEFAULT_REPEAT_HARD_STOP_THRESHOLD = 3


@dataclass(frozen=True)
class ToolBatchResult:
    terminal_result: HarnessAttemptResult | None
    tool_calls_executed: int
    metadata: dict[str, object]


class ConcurrentToolBatchExecutor:
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
        if max_parallel_tool_calls <= 0:
            raise ValueError("max_parallel_tool_calls must be positive")
        if repeat_hard_stop_threshold <= 0:
            raise ValueError("repeat_hard_stop_threshold must be positive")
        self._policy_engine = policy_engine
        self._tool_gateway = tool_gateway
        self._model_step = model_step
        self._verifier = verifier
        self._parallel_safe_tools = parallel_safe_tools
        self._parallel_batch_limits = dict(parallel_batch_limits or {})
        invalid_limits = (
            not name.strip() or limit <= 0
            for name, limit in self._parallel_batch_limits.items()
        )
        if any(invalid_limits):
            raise ValueError("parallel batch limits require named tools and positive limits")
        self._max_parallel_tool_calls = max_parallel_tool_calls
        self._repeat_hard_stop_threshold = repeat_hard_stop_threshold

    def can_execute(
        self,
        tool_calls: tuple[ToolCall, ...],
        *,
        execute_all: bool,
        first_execution_started: bool,
    ) -> bool:
        return (
            execute_all
            and not first_execution_started
            and len(tool_calls) > 1
            and self._max_parallel_tool_calls > 1
            and all(call.name in self._parallel_safe_tools for call in tool_calls)
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
        first_selection: ToolCallSelection | None,
    ) -> ToolBatchResult:
        batch_event_start = len(emitted_events)
        exceeded = self._exceeded_batch_limit(tool_calls)
        if exceeded is not None:
            tool_name, limit = exceeded
            return self._terminal(
                summary=f"parallel batch limit exceeded before {tool_name} started",
                completion=completion,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                metadata={
                    **metadata,
                    "stop_reason": "parallel_batch_limit_exceeded",
                    "limited_tool_name": tool_name,
                    "parallel_batch_limit": limit,
                    "remaining_tool_call_count": len(tool_calls),
                },
            )
        seen = set(fingerprints)
        loop_guard_counts = _loop_guard_counts(metadata)
        metadata = {**metadata, "loop_guard_counts": dict(loop_guard_counts)}
        duplicate_indices: set[int] = set()
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
            fingerprint = action_fingerprint(tool_call)
            if fingerprint in seen:
                loop_guard_counts[fingerprint] = (
                    loop_guard_counts.get(fingerprint, 0) + 1
                )
                duplicate_indices.add(index)
            seen.add(fingerprint)
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
                if decision.decision is PolicyDecisionType.DENY and decision.recoverable:
                    observation = recoverable_policy_deny_observation(
                        context,
                        messages=messages,
                        tool_call=tool_call,
                        decision=decision,
                        retained_tool_calls=(tool_call,),
                        model_step=self._model_step,
                        verifier=self._verifier,
                        emitted_events=emitted_events,
                    )
                    observations.append((tool_call, observation.result))
                    metadata = policy_recovery_metadata({**metadata, **observation.metadata})
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
        batch_metadata = {
            **metadata,
            "loop_guard_counts": loop_guard_counts,
            "parallel_batch_size": len(tool_calls),
            "parallelism_limit": self._max_parallel_tool_calls,
        }
        executable_calls = tuple(
            call for idx, call in enumerate(tool_calls) if idx not in duplicate_indices
        )
        for tool_call in tool_calls:
            emitted_events.append(_started_event(context, tool_call))
        executed_results = self._execute_all(executable_calls)
        results = _merge_results(tool_calls, executable_calls, executed_results, duplicate_indices)
        failed_names: list[str] = []
        for tool_call, tool_result in zip(tool_calls, results, strict=True):
            execution = record_tool_result(
                context,
                tool_call,
                tool_result,
                verifier=self._verifier,
                emitted_events=emitted_events,
            )
            tool_calls_executed += 1
            fingerprints.add(action_fingerprint(tool_call))
            observations.append((tool_call, tool_result))
            self._model_step.append_tool_result(
                messages,
                tool_call=tool_call,
                tool_result=tool_result,
                created_at=context.attempt.started_at,
            )
            if tool_result.status is not ToolCallStatus.EXECUTED:
                failed_names.append(tool_call.name)
            batch_metadata = {**batch_metadata, **execution.metadata}
            batch_metadata = aggregate_subagent_metadata(
                batch_metadata,
                tool_result,
            )
        batch_metadata = update_batch_observation_progress(
            batch_metadata,
            observations,
            emitted_events[batch_event_start:],
            threshold=self._repeat_hard_stop_threshold,
        )
        if failed_names:
            prior_failures = batch_metadata.get("recoverable_tool_failure_count", 0)
            failure_count = (
                prior_failures + len(failed_names)
                if isinstance(prior_failures, int) and not isinstance(prior_failures, bool)
                else len(failed_names)
            )
            return ToolBatchResult(
                None,
                tool_calls_executed,
                {
                    **batch_metadata,
                    "recoverable_tool_failure_count": failure_count,
                    "failed_tool_names": failed_names,
                },
            )
        return ToolBatchResult(None, tool_calls_executed, batch_metadata)

    def _exceeded_batch_limit(
        self,
        tool_calls: tuple[ToolCall, ...],
    ) -> tuple[str, int] | None:
        counts = Counter(call.name for call in tool_calls)
        for tool_name in sorted(counts):
            limit = self._parallel_batch_limits.get(tool_name)
            if limit is not None and counts[tool_name] > limit:
                return tool_name, limit
        return None

    def _execute_all(self, tool_calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
        with ThreadPoolExecutor(max_workers=self._max_parallel_tool_calls) as executor:
            futures = [executor.submit(self._tool_gateway.execute, call) for call in tool_calls]
        return tuple(
            _future_result(call, future) for call, future in zip(tool_calls, futures, strict=True)
        )

    @staticmethod
    def _terminal(
        *,
        summary: str,
        completion: ModelCompletion,
        emitted_events: list[HarnessEventDraft],
        model_calls_used: int,
        tool_calls_executed: int,
        metadata: dict[str, object],
    ) -> ToolBatchResult:
        return ToolBatchResult(
            build_attempt_result(
                outcome=HarnessAttemptOutcome.FAILED,
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


def selection_evidence(
    *, index: int, count: int, first_selection: ToolCallSelection | None
) -> tuple[str, dict[str, object]]:
    if index == 0 and first_selection is not None:
        return first_selection.summary, first_selection.metadata
    return "selected provider-order tool call", {
        "selected_index": index,
        "candidate_count": count,
    }


def _started_event(context: HarnessContext, tool_call: ToolCall) -> HarnessEventDraft:
    return HarnessEventDraft(
        event_type=EventType.TOOL_EXECUTION_STARTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": context.attempt.number,
            "tool_name": tool_call.name,
            "tool_call_id": str(tool_call.tool_call_id),
        },
    )


def _future_result(tool_call: ToolCall, future: Future[ToolResult]) -> ToolResult:
    try:
        return future.result()
    except Exception as exc:
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            metadata={"reason": "tool_gateway_error", "detail": str(exc)},
        )


def _loop_guard_counts(metadata: Mapping[str, object]) -> dict[str, int]:
    raw = metadata.get("loop_guard_counts")
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool)}
    return {}


def _merge_results(
    tool_calls: tuple[ToolCall, ...],
    executable_calls: tuple[ToolCall, ...],
    executed_results: tuple[ToolResult, ...],
    duplicate_indices: set[int],
) -> tuple[ToolResult, ...]:
    if not duplicate_indices:
        return executed_results
    results: list[ToolResult] = []
    exec_iter = iter(executed_results)
    for index, tool_call in enumerate(tool_calls):
        if index in duplicate_indices:
            results.append(
                ToolResult(
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
                    },
                )
            )
        else:
            results.append(next(exec_iter))
    return tuple(results)
