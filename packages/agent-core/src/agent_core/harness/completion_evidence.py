from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCallStatus
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.completion_blocking import (
    append_missing_evidence_observation,
    blocked_completion_reason,
    blocked_completion_summary,
    completion_evidence_failure_outcome,
    completion_evidence_observation_count,
    current_task_plan,
)
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)
from agent_core.harness.tool_batch import ToolBatchResult


@dataclass(frozen=True)
class CompletionEvidenceStatus:
    satisfied: bool
    missing: tuple[str, ...]
    fingerprint: str
    open_plan_steps: tuple[str, ...] = ()


_PLAN_COMPLETION_REQUIREMENT = "task_plan_closed"


def evaluate_context_completion_evidence(
    context: HarnessContext,
    emitted_events: Iterable[HarnessEventDraft],
) -> CompletionEvidenceStatus:
    status = evaluate_completion_evidence(
        context.task.agent_definition,
        (*context.completion_evidence_events, *emitted_events),
    )
    plan = current_task_plan(context, emitted_events)
    if not plan.open_step_ids:
        return status
    missing = (*status.missing, _PLAN_COMPLETION_REQUIREMENT)
    fingerprint = sha256(
        json.dumps(
            {"evidence": status.fingerprint, "open_plan_steps": plan.open_step_ids},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return CompletionEvidenceStatus(False, missing, fingerprint, plan.open_step_ids)


def persisted_completion_evidence_events(
    events: Iterable[SessionEvent],
) -> tuple[HarnessEventDraft, ...]:
    return tuple(
        HarnessEventDraft(
            event_type=event.event_type,
            actor=event.actor,
            payload=event.payload,
        )
        for event in events
    )


def evaluate_completion_evidence(
    definition: AgentDefinition | None,
    events: Iterable[HarnessEventDraft],
) -> CompletionEvidenceStatus:
    if definition is None or not definition.completion_contract.required_evidence:
        return CompletionEvidenceStatus(True, (), "no-contract")

    typed: set[str] = set()
    tags: set[str] = set()
    validator_outcomes: set[str] = set()
    capability_results: set[str] = set()
    successful_tool_call_ids: set[str] = set()
    for event in events:
        if event.event_type is EventType.TOOL_EXECUTION_COMPLETED:
            if not _trusted_tool_execution(event):
                continue
            tool_call_id = event.payload.get("tool_call_id")
            if isinstance(tool_call_id, str) and tool_call_id.strip():
                successful_tool_call_ids.add(tool_call_id.strip())
            metadata = _mapping(event.payload.get("metadata"))
            typed.update(_values(metadata.get("typed_evidence")))
            tags.update(_values(metadata.get("tool_tags")))
            capability_results.update(_values(metadata.get("capability_result")))
        elif event.event_type is EventType.TESTS_COMPLETED:
            if not _trusted_validator_test(event, successful_tool_call_ids):
                continue
            metadata = _mapping(event.payload.get("metadata"))
            explicit = metadata.get("validator_outcome")
            passed = event.payload.get("passed")
            if (
                isinstance(explicit, str)
                and explicit.strip()
                and isinstance(passed, bool)
                and (explicit.strip() == "passed") is passed
            ):
                validator_outcomes.add(explicit.strip())

    missing: list[str] = []
    for requirement in definition.completion_contract.required_evidence:
        if not _requirement_satisfied(
            requirement,
            typed=typed,
            tags=tags,
            validator_outcomes=validator_outcomes,
            capability_results=capability_results,
        ):
            missing.append(requirement.evidence_id)
    fingerprint = sha256(
        json.dumps(
            {
                "typed": sorted(typed),
                "tags": sorted(tags),
                "validator_outcomes": sorted(validator_outcomes),
                "capability_results": sorted(capability_results),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return CompletionEvidenceStatus(not missing, tuple(missing), fingerprint)


def _trusted_tool_execution(event: HarnessEventDraft) -> bool:
    return (
        event.actor is EventActor.TOOL
        and event.payload.get("status") == ToolCallStatus.EXECUTED.value
    )


def _trusted_validator_test(
    event: HarnessEventDraft,
    successful_tool_call_ids: set[str],
) -> bool:
    if event.actor is not EventActor.HARNESS:
        return False
    tool_call_id = event.payload.get("tool_call_id")
    if not isinstance(tool_call_id, str) or tool_call_id.strip() not in successful_tool_call_ids:
        return False
    tool_tags = _values(event.payload.get("tool_tags"))
    return "validator" in tool_tags


def gate_completed_terminal_result(
    terminal_result: HarnessAttemptResult,
    request_next_completion: Callable[..., HarnessAttemptResult],
    context: HarnessContext,
    messages: list[SessionMessage],
    emitted_events: list[HarnessEventDraft],
    fingerprints: set[str],
) -> HarnessAttemptResult:
    if terminal_result.outcome is not HarnessAttemptOutcome.COMPLETED:
        return terminal_result
    return complete_without_tools(
        context,
        messages=messages,
        emitted_events=emitted_events,
        model_calls_used=_non_negative_int(terminal_result.metadata.get("model_calls_used")),
        tool_calls_executed=_non_negative_int(
            terminal_result.metadata.get("tool_calls_executed")
        ),
        metadata=dict(terminal_result.metadata),
        assistant_message=str(terminal_result.metadata.get("assistant_message", "")),
        fingerprints=fingerprints,
        request_next_completion=request_next_completion,
    )


def completion_evidence_metadata(
    context: HarnessContext,
    emitted_events: Iterable[HarnessEventDraft],
    metadata: Mapping[str, object],
) -> dict[str, object]:
    return _completion_status_metadata(
        evaluate_context_completion_evidence(context, emitted_events), metadata
    )


def continue_after_tool_batch(
    context: HarnessContext,
    *,
    messages: list[SessionMessage],
    completion: ModelCompletion,
    emitted_events: list[HarnessEventDraft],
    batch: ToolBatchResult,
    model_calls_used: int,
    fingerprints: set[str],
    request_terminal_synthesis: Callable[..., HarnessAttemptResult],
    request_next_completion: Callable[..., HarnessAttemptResult],
) -> HarnessAttemptResult:
    if batch.terminal_result is not None:
        return gate_completed_terminal_result(
            batch.terminal_result,
            request_next_completion,
            context,
            messages,
            emitted_events,
            fingerprints,
        )
    metadata = completion_evidence_metadata(context, emitted_events, batch.metadata)
    if _needs_terminal_synthesis(batch.metadata):
        return request_terminal_synthesis(
            context,
            messages=messages,
            emitted_events=emitted_events,
            model_calls_used=model_calls_used,
            tool_calls_executed=batch.tool_calls_executed,
            metadata=metadata,
            fallback_message=completion.assistant_message.content,
        )
    return request_next_completion(
        context,
        messages=messages,
        emitted_events=emitted_events,
        model_calls_used=model_calls_used,
        tool_calls_executed=batch.tool_calls_executed,
        fingerprints=fingerprints,
        metadata=metadata,
        fallback_message=completion.assistant_message.content,
    )


def should_use_provisional_final(
    context: HarnessContext,
    emitted_events: Iterable[HarnessEventDraft],
    *,
    allow_tools: bool,
    has_tool_calls: bool,
    tool_calls_executed: int,
    compaction_happened: bool,
    compaction_count: object,
) -> bool:
    definition = context.task.agent_definition
    contract_required = bool(
        definition is not None and definition.completion_contract.required_evidence
    )
    compacted_before = (
        isinstance(compaction_count, int)
        and not isinstance(compaction_count, bool)
        and compaction_count > 0
    )
    return (
        not has_tool_calls
        and allow_tools
        and not contract_required
        and evaluate_context_completion_evidence(context, emitted_events).satisfied
        and (tool_calls_executed > 0 or compaction_happened or compacted_before)
    )


def complete_without_tools(
    context: HarnessContext,
    *,
    messages: list[SessionMessage],
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
    assistant_message: str,
    fingerprints: set[str],
    request_next_completion: Callable[..., HarnessAttemptResult],
) -> HarnessAttemptResult:
    status = evaluate_context_completion_evidence(context, emitted_events)
    observation_count = completion_evidence_observation_count(messages, metadata)
    metadata = _completion_status_metadata(status, metadata)
    if status.satisfied:
        return build_attempt_result(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary=(
                "model completed without tool calls"
                if tool_calls_executed == 0
                else "tool sequence completed with final answer"
            ),
            assistant_message=assistant_message,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            emitted_events=emitted_events,
            metadata=metadata,
        )
    if observation_count >= 1:
        return build_attempt_result(
            outcome=completion_evidence_failure_outcome(status.open_plan_steps),
            summary=blocked_completion_summary(status.open_plan_steps),
            assistant_message=assistant_message,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            emitted_events=emitted_events,
            metadata={
                **metadata,
                "completion_evidence_observation_count": observation_count,
                "stop_reason": blocked_completion_reason(status.open_plan_steps),
            },
        )
    append_missing_evidence_observation(
        messages,
        missing=status.missing,
        open_plan_steps=status.open_plan_steps,
        definition=context.task.agent_definition,
        trusted_evidence_tools=context.task.trusted_evidence_tools,
        created_at=context.attempt.started_at,
    )
    return request_next_completion(
        context,
        messages=messages,
        emitted_events=emitted_events,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        fingerprints=fingerprints,
        metadata={
            **metadata,
            "completion_evidence_observation_count": observation_count + 1,
        },
        fallback_message=assistant_message,
    )


def prepare_terminal_synthesis_evidence(
    context: HarnessContext,
    *,
    messages: list[SessionMessage],
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
    fallback_message: str,
    fingerprints: set[str],
    request_next_completion: Callable[..., HarnessAttemptResult],
) -> HarnessAttemptResult | None:
    status = evaluate_context_completion_evidence(context, emitted_events)
    if status.satisfied:
        return None
    observation_count = completion_evidence_observation_count(messages, metadata)
    if observation_count >= 1:
        return build_attempt_result(
            outcome=completion_evidence_failure_outcome(status.open_plan_steps),
            summary=blocked_completion_summary(status.open_plan_steps),
            assistant_message=fallback_message,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            emitted_events=emitted_events,
            metadata={
                **metadata,
                "completion_evidence_satisfied": False,
                "completion_evidence_missing": list(status.missing),
                "task_plan_open_steps": list(status.open_plan_steps),
                "stop_reason": blocked_completion_reason(status.open_plan_steps),
            },
        )
    append_missing_evidence_observation(
        messages,
        missing=status.missing,
        open_plan_steps=status.open_plan_steps,
        definition=context.task.agent_definition,
        trusted_evidence_tools=context.task.trusted_evidence_tools,
        created_at=context.attempt.started_at,
    )
    return request_next_completion(
        context,
        messages=messages,
        emitted_events=emitted_events,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        fingerprints=fingerprints,
        metadata={
            **metadata,
            "completion_evidence_observation_count": observation_count + 1,
        },
        fallback_message=fallback_message,
    )


def terminal_synthesis_completion_evidence(
    context: HarnessContext,
    *,
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
    assistant_message: str,
) -> HarnessAttemptResult | None:
    status = evaluate_context_completion_evidence(context, emitted_events)
    if status.satisfied:
        return None
    return build_attempt_result(
        outcome=completion_evidence_failure_outcome(status.open_plan_steps),
        summary=blocked_completion_summary(status.open_plan_steps),
        assistant_message=assistant_message,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        emitted_events=emitted_events,
        metadata={
            **metadata,
            "completion_evidence_satisfied": False,
            "completion_evidence_missing": list(status.missing),
            "task_plan_open_steps": list(status.open_plan_steps),
            "stop_reason": blocked_completion_reason(status.open_plan_steps),
        },
    )


def _needs_terminal_synthesis(metadata: Mapping[str, object]) -> bool:
    return metadata.get("validator_correction_required") is True or metadata.get(
        "tool_loop_no_progress"
    ) is True or metadata.get("policy_recovery_terminal_synthesis") is True


def _completion_status_metadata(
    status: CompletionEvidenceStatus,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    return {
        **metadata,
        "completion_evidence_satisfied": status.satisfied,
        "completion_evidence_missing": list(status.missing),
        "completion_evidence_fingerprint": status.fingerprint,
        **(
            {"task_plan_open_steps": list(status.open_plan_steps)}
            if status.open_plan_steps
            else {}
        ),
    }


def _requirement_satisfied(
    requirement: CompletionEvidenceRequirement,
    *,
    typed: set[str],
    tags: set[str],
    validator_outcomes: set[str],
    capability_results: set[str],
) -> bool:
    return bool(
        set(requirement.typed_evidence) & typed
        or set(requirement.tool_tags) & tags
        or (
            requirement.validator_outcome is not None
            and requirement.validator_outcome in validator_outcomes
        )
        or (
            requirement.capability_result is not None
            and requirement.capability_result in capability_results
        )
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _values(value: object) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, Mapping):
        for key in ("id", "name", "type", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return {candidate.strip()}
        return set()
    if isinstance(value, Iterable) and not isinstance(value, bytes):
        values: set[str] = set()
        for item in value:
            values.update(_values(item))
        return values
    return set()
