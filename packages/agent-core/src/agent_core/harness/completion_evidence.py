from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.harness.models import HarnessEventDraft


@dataclass(frozen=True)
class CompletionEvidenceStatus:
    satisfied: bool
    missing: tuple[str, ...]
    fingerprint: str


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
    for event in events:
        if event.event_type is EventType.TOOL_EXECUTION_COMPLETED:
            metadata = _mapping(event.payload.get("metadata"))
            typed.update(_values(metadata.get("typed_evidence")))
            tags.update(_values(metadata.get("tool_tags")))
            capability_results.update(_values(metadata.get("capability_result")))
            _add_validator_outcome(metadata, tags, validator_outcomes)
        elif event.event_type is EventType.TESTS_COMPLETED:
            metadata = _mapping(event.payload.get("metadata"))
            explicit = metadata.get("validator_outcome")
            if isinstance(explicit, str) and explicit.strip():
                validator_outcomes.add(explicit.strip())
            if "validator" in _values(metadata.get("tool_tags")):
                passed = event.payload.get("passed")
                if isinstance(passed, bool):
                    validator_outcomes.add("passed" if passed else "failed")

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


def _add_validator_outcome(
    metadata: Mapping[str, object],
    tags: set[str],
    outcomes: set[str],
) -> None:
    explicit = metadata.get("validator_outcome")
    if isinstance(explicit, str) and explicit.strip():
        outcomes.add(explicit.strip())
    if "validator" not in tags:
        return
    result = metadata.get("validator_result")
    if isinstance(result, Mapping) and isinstance(result.get("passed"), bool):
        outcomes.add("passed" if result["passed"] else "failed")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


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
