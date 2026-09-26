"""Small deterministic gates for skill usage and final-answer acceptance."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_core.harness.evidence_ledger import EvidenceLedger
from agent_core.harness.models import SkillReadRequirement
from agent_core.harness.task_contracts import (
    TaskAcceptanceContract,
    infer_task_contract,
)


@dataclass(frozen=True)
class AnswerQuality:
    passed: bool
    reason: str
    missing_requirements: tuple[str, ...] = ()


def missing_selected_skills(
    selected: tuple[str, ...],
    metadata: Mapping[str, object],
    requirements: Sequence[SkillReadRequirement] = (),
) -> tuple[str, ...]:
    if not selected:
        return ()
    raw = metadata.get("skill_reads")
    reads = raw if isinstance(raw, dict) else {}
    by_component = {item.component: item for item in requirements}
    return tuple(
        skill
        for skill in selected
        if not _skill_read_matches(reads.get(skill), by_component.get(skill))
    )


def _skill_read_matches(
    raw: object,
    requirement: SkillReadRequirement | None,
) -> bool:
    if requirement is None:
        return raw is not None
    if not isinstance(raw, Mapping):
        return False
    expected = {
        "skill_name": requirement.name,
        "skill_id": requirement.skill_id,
        "skill_version": requirement.version,
        "skill_version_id": requirement.version_id,
        "skill_digest": requirement.digest,
    }
    return all(value is None or raw.get(key) == value for key, value in expected.items())


def acceptance_contract(user_input: str) -> TaskAcceptanceContract:
    return infer_task_contract(user_input)


def is_substantive_request(user_input: str) -> bool:
    return acceptance_contract(user_input).min_characters > 1


def evaluate_answer(
    user_input: str,
    answer: str,
    *,
    evidence: EvidenceLedger | None = None,
    contract: TaskAcceptanceContract | None = None,
) -> AnswerQuality:
    stripped = answer.strip()
    if not stripped:
        return AnswerQuality(False, "empty_answer", ("non_empty_answer",))
    contract = contract or acceptance_contract(user_input)
    missing: list[str] = []
    if len(stripped) < contract.min_characters:
        missing.append(f"minimum_detail:{contract.min_characters}_characters")
    if contract.max_characters is not None and len(stripped) > contract.max_characters:
        missing.append(f"maximum_length:{contract.max_characters}_characters")
    for term in contract.required_answer_terms:
        if term.casefold() not in stripped.casefold():
            missing.append(f"required_answer_term:{term}")
    lines = answer.splitlines()
    structured = sum(
        1 for line in lines if line.lstrip().startswith(("#", "-", "*", "1.", "一、", "二、"))
    )
    if contract.require_structure and (len(lines) < 3 or structured == 0):
        missing.append("requested_structure")
    ledger = evidence or EvidenceLedger()
    if contract.require_evidence_reference and not ledger.has_evidence:
        missing.append("verified_evidence")
    elif contract.require_matching_citation and not ledger.cited_refs(stripped):
        missing.append("citation_matching_collected_evidence")
    if contract.require_artifact and not ledger.artifact_refs:
        missing.append("required_artifact")
    if contract.require_matching_citation and _unsupported_urls(stripped, ledger.evidence_refs):
        missing.append("citation_uses_exact_collected_url")
    if missing:
        reason = (
            "deliverable_too_shallow"
            if missing[0].startswith("minimum_detail")
            else "deliverable_too_long"
            if missing[0].startswith("maximum_length")
            else "deliverable_missed_goal"
            if missing[0].startswith("required_answer_term")
            else "deliverable_not_structured"
            if missing[0] == "requested_structure"
            else "deliverable_missing_evidence"
        )
        return AnswerQuality(False, reason, tuple(missing))
    return AnswerQuality(True, "acceptance_contract_satisfied")


_URL_PATTERN = re.compile(r"https?://[^\s<>\])]+")
_TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？)]}"


def _unsupported_urls(answer: str, evidence_refs: tuple[str, ...]) -> tuple[str, ...]:
    """Reject invented or annotation-extended URLs while allowing normal Markdown closers."""

    supported = set(evidence_refs)
    candidates = {
        match.group(0).rstrip(_TRAILING_URL_PUNCTUATION) for match in _URL_PATTERN.finditer(answer)
    }
    return tuple(sorted(candidate for candidate in candidates if candidate not in supported))
