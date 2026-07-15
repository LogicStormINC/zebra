from collections import Counter
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
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
from agent_core.harness.subagent_metadata import aggregate_subagent_metadata
from agent_core.harness.tool_execution import record_tool_result
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.tool_gateway import ToolGatewayPort


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
    ) -> None:
        if max_parallel_tool_calls <= 0:
            raise ValueError("max_parallel_tool_calls must be positive")
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
        tool_call_limit: int,
        fingerprints: set[str],
        metadata: dict[str, object],
        first_selection: ToolCallSelection | None,
    ) -> ToolBatchResult:
        if tool_calls_executed + len(tool_calls) > tool_call_limit:
            return self._terminal(
                summary="tool call budget exhausted before concurrent batch started",
                completion=completion,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                metadata={
                    **metadata,
                    "stop_reason": "tool_call_budget_exhausted",
                    "remaining_tool_call_count": len(tool_calls),
                },
            )
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
                        "arguments": tool_call.arguments,
                        "selection_summary": summary,
                        "selection_metadata": selection_metadata,
                    },
                )
            )
            fingerprint = action_fingerprint(tool_call)
            if fingerprint in seen:
                return self._terminal(
                    summary=f"repeated tool call blocked: {tool_call.name}",
                    completion=completion,
                    emitted_events=emitted_events,
                    model_calls_used=model_calls_used,
                    tool_calls_executed=tool_calls_executed,
                    metadata={
                        **metadata,
                        "stop_reason": "repeated_tool_call",
                        "remaining_tool_call_count": len(tool_calls),
                    },
                )
            seen.add(fingerprint)
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
        batch_metadata = {
            **metadata,
            "parallel_batch_size": len(tool_calls),
            "parallelism_limit": self._max_parallel_tool_calls,
        }
        for tool_call in tool_calls:
            emitted_events.append(_started_event(context, tool_call))
        results = self._execute_all(tool_calls)
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
        if failed_names:
            return self._terminal(
                summary="concurrent tool batch failed: " + ", ".join(failed_names),
                completion=completion,
                emitted_events=emitted_events,
                model_calls_used=model_calls_used,
                tool_calls_executed=tool_calls_executed,
                metadata={
                    **batch_metadata,
                    "stop_reason": "concurrent_tool_failure",
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
