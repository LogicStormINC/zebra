from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCallStatus
from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
)


@dataclass(frozen=True)
class CompletionEvidenceStatus:
    satisfied: bool
    missing: tuple[str, ...]
    fingerprint: str


def evaluate_context_completion_evidence(
    context: HarnessContext,
    emitted_events: Iterable[HarnessEventDraft],
) -> CompletionEvidenceStatus:
    return evaluate_completion_evidence(
        context.task.agent_definition,
        (*context.completion_evidence_events, *emitted_events),
    )


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
    complete_without_tools: Callable[..., HarnessAttemptResult],
    context: HarnessContext,
    messages: list[SessionMessage],
    emitted_events: list[HarnessEventDraft],
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
    )


def append_missing_evidence_observation(
    messages: list[SessionMessage],
    *,
    missing: tuple[str, ...],
    created_at: datetime,
) -> None:
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
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\nUse available tools to obtain the missing typed evidence. "
                "Do not claim completion until the completion contract is satisfied."
            ),
            created_at=created_at,
            metadata={"missing_completion_evidence": list(missing)},
        )
    )


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
