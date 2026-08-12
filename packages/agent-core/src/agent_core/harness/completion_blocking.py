from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime

from agent_core.domain.agent_definitions import AgentDefinition
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.plans import SessionPlan
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
) -> None:
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
                        "trusted_evidence_tools": _trusted_evidence_tools(
                            definition,
                            missing,
                            trusted_evidence_tools,
                        ),
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


def blocked_completion_reason(open_plan_steps: tuple[str, ...]) -> str:
    return "task_plan_incomplete" if open_plan_steps else "completion_evidence_missing"


def blocked_completion_summary(open_plan_steps: tuple[str, ...]) -> str:
    return (
        "durable task plan still has open steps"
        if open_plan_steps
        else "completion evidence contract is not satisfied"
    )
