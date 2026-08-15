from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime

from agent_core.domain.agent_definitions import AgentDefinition
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.plans import SessionPlan
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.coverage_verdict import CompletionEvidenceStatus
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)


def current_task_plan(
    context: HarnessContext,
    emitted_events: Iterable[HarnessEventDraft],
) -> SessionPlan:
    plan = context.session.task_plan
    if not plan.steps and plan.updated_at is None:
        plan = context.task.task_plan
    for event in emitted_events:
        if event.event_type is EventType.PLAN_UPDATED:
            plan = SessionPlan.model_validate({"steps": event.payload.get("steps", ())})
    return plan


def enforce_plan_completion_coherence(
    context: HarnessContext,
    result: HarnessAttemptResult,
) -> HarnessAttemptResult:
    if result.outcome is not HarnessAttemptOutcome.COMPLETED:
        return result
    plan = current_task_plan(context, result.emitted_events)
    if context.task.plan_required and not plan.steps:
        return replace(
            result,
            outcome=HarnessAttemptOutcome.FAILED,
            summary="required durable Plan was not created",
            metadata={
                **result.metadata,
                "stop_reason": "required_plan_not_created",
            },
        )
    if not plan.open_step_ids:
        return result
    return replace(
        result,
        outcome=HarnessAttemptOutcome.SUSPENDED,
        summary="durable task plan still has open steps",
        metadata={
            **result.metadata,
            "stop_reason": "task_plan_incomplete",
            "task_plan_open_steps": list(plan.open_step_ids),
        },
    )


def append_missing_evidence_observation(
    messages: list[SessionMessage],
    *,
    missing: tuple[str, ...],
    open_plan_steps: tuple[str, ...],
    definition: AgentDefinition | None,
    trusted_evidence_tools: Mapping[str, tuple[str, ...]],
    created_at: datetime,
) -> tuple[str, ...]:
    producer_guidance = _trusted_evidence_tools(
        definition,
        missing,
        trusted_evidence_tools,
    )
    guidance = (
        "Use agent.plan to continue the remaining work, mark finished steps completed, or "
        "mark obsolete steps cancelled. "
        if open_plan_steps
        else "Use available tools to obtain the missing typed evidence. "
    )
    messages.append(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.SYSTEM,
            content=(
                "Runtime completion-evidence observation: "
                + json.dumps(
                    {
                        "type": "missing_completion_evidence",
                        "missing": list(missing),
                        "open_plan_steps": list(open_plan_steps),
                        "trusted_evidence_tools": producer_guidance,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
                + guidance
                + "Do not claim completion until the runtime completion conditions are satisfied."
            ),
            created_at=created_at,
            metadata={"missing_completion_evidence": list(missing)},
        )
    )
    return tuple(
        dict.fromkeys(
            tool
            for item in producer_guidance
            for tool in _string_list(item.get("tools"))
            if isinstance(tool, str)
        )
    )


def matching_evidence_producers(
    definition: AgentDefinition | None,
    missing: tuple[str, ...],
    trusted_evidence_tools: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Currently-advertised trusted producer tools that can satisfy at least
    one of the missing typed-evidence requirements. A prompt-only correction
    (no matching producer) must never dispatch; the correction budget may
    increment only when at least one producer exists."""
    return tuple(
        dict.fromkeys(
            tool
            for item in _trusted_evidence_tools(definition, missing, trusted_evidence_tools)
            for tool in _string_list(item.get("tools"))
            if isinstance(tool, str)
        )
    )


def schedule_evidence_correction(
    context: HarnessContext,
    *,
    status: CompletionEvidenceStatus,
    messages: list[SessionMessage],
    emitted_events: list[HarnessEventDraft],
    model_calls_used: int,
    tool_calls_executed: int,
    metadata: dict[str, object],
    observation_count: int,
    assistant_message: str,
    fingerprints: set[str],
    request_next_completion: Callable[..., HarnessAttemptResult],
    include_evidence_detail: bool = False,
) -> HarnessAttemptResult:
    """Typed-tool-only correction scheduling (P1-3).

    Only when at least one matching currently-advertised trusted producer
    exists may the correction budget increment and the next dispatch use
    tool_choice=required with only those tools. A prompt-only correction
    fails closed with the legacy non-retryable code without dispatching.
    Open-plan corrections stay separate (plan behavior unchanged).
    """
    if not status.open_plan_steps and not matching_evidence_producers(
        context.task.agent_definition,
        status.missing,
        context.task.trusted_evidence_tools,
    ):
        detail = (
            {
                "completion_evidence_satisfied": False,
                "completion_evidence_missing": list(status.missing),
                "task_plan_open_steps": list(status.open_plan_steps),
            }
            if include_evidence_detail
            else {}
        )
        return build_attempt_result(
            outcome=completion_evidence_failure_outcome(status.open_plan_steps),
            summary=blocked_completion_summary(status.open_plan_steps),
            assistant_message=assistant_message,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            emitted_events=emitted_events,
            metadata={
                **metadata,
                **detail,
                "completion_evidence_observation_count": observation_count,
                "stop_reason": blocked_completion_reason(
                    status.open_plan_steps,
                    correction_attempted=False,
                ),
            },
        )
    required_tools = append_missing_evidence_observation(
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
            **(
                {"required_evidence_tool_names": required_tools}
                if required_tools
                else {}
            ),
        },
        fallback_message=assistant_message,
    )


def _trusted_evidence_tools(
    definition: AgentDefinition | None,
    missing: tuple[str, ...],
    tools: Mapping[str, tuple[str, ...]],
) -> list[dict[str, object]]:
    if definition is None:
        return []
    requirements = {
        requirement.evidence_id: requirement
        for requirement in definition.completion_contract.required_evidence
    }
    guidance: list[dict[str, object]] = []
    for evidence_id in missing:
        requirement = requirements.get(evidence_id)
        if requirement is None or not requirement.typed_evidence:
            continue
        matching_tools = sorted(
            tool_name
            for tool_name, labels in tools.items()
            if set(requirement.typed_evidence) & set(labels)
        )
        if matching_tools:
            guidance.append(
                {
                    "evidence_id": evidence_id,
                    "typed_evidence": list(requirement.typed_evidence),
                    "tools": matching_tools,
                }
            )
    return guidance


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def completion_evidence_observation_count(
    messages: Iterable[SessionMessage],
    metadata: dict[str, object],
) -> int:
    count = metadata.get("completion_evidence_observation_count")
    recorded = count if isinstance(count, int) and not isinstance(count, bool) else 0
    return max(
        recorded,
        sum("missing_completion_evidence" in message.metadata for message in messages),
    )


def completion_evidence_failure_outcome(
    open_plan_steps: tuple[str, ...],
) -> HarnessAttemptOutcome:
    return HarnessAttemptOutcome.SUSPENDED if open_plan_steps else HarnessAttemptOutcome.FAILED


def blocked_completion_reason(
    open_plan_steps: tuple[str, ...],
    *,
    correction_attempted: bool = False,
) -> str:
    if open_plan_steps:
        return "task_plan_incomplete"
    if correction_attempted:
        return "completion_evidence_missing_after_correction"
    return "completion_evidence_missing"


def blocked_completion_summary(open_plan_steps: tuple[str, ...]) -> str:
    return (
        "durable task plan still has open steps"
        if open_plan_steps
        else "completion evidence contract is not satisfied"
    )
