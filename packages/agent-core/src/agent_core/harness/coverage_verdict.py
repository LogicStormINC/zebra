"""Safe coverage status metadata and terminal verdict builders.

Wave 5 Phase 2: the completion-evidence evaluator reports safe counts (no
requirement IDs) and the Task terminal carries only a safe coverage verdict
(status/counts/message). Private requirement IDs, evidence refs, digests and
diagnostics stay in the private metadata and never enter the public summary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

PLAN_COMPLETION_REQUIREMENT = "task_plan_closed"


@dataclass(frozen=True)
class CompletionEvidenceStatus:
    satisfied: bool
    missing: tuple[str, ...]
    fingerprint: str
    open_plan_steps: tuple[str, ...] = ()
    required: int = 0


def completion_status_metadata(
    status: CompletionEvidenceStatus,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    missing_count = len(status.missing)
    return {
        **metadata,
        "completion_evidence_satisfied": status.satisfied,
        "completion_evidence_missing": list(status.missing),
        "completion_evidence_fingerprint": status.fingerprint,
        "completion_evidence_required_count": status.required,
        "completion_evidence_satisfied_count": max(0, status.required - missing_count),
        "completion_evidence_missing_count": missing_count,
        **(
            {"task_plan_open_steps": list(status.open_plan_steps)}
            if status.open_plan_steps
            else {}
        ),
    }


def safe_coverage_verdict(metadata: Mapping[str, object]) -> dict[str, object] | None:
    """Safe terminal coverage verdict: status, counts and one message only."""
    required = metadata.get("completion_evidence_required_count")
    satisfied = metadata.get("completion_evidence_satisfied_count")
    missing = metadata.get("completion_evidence_missing_count")
    return _verified_verdict(required, satisfied, missing)


def sanitize_public_coverage_verdict(raw: object) -> dict[str, object] | None:
    """Public-projection sanitizer for a terminal coverage verdict.

    Never trusts or forwards the source dict or source message. The exact
    five-field object is rebuilt from validated counts and a fixed message
    derived from the validated status/counts. Malformed verdicts (unknown
    status, wrong types, bool-as-int, negative or inconsistent counts, or a
    status that contradicts the counts) fail closed by omitting the verdict.
    """
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if status not in {"complete", "partial", "missing"}:
        return None
    verdict = _verified_verdict(
        raw.get("required_count"),
        raw.get("satisfied_count"),
        raw.get("missing_count"),
    )
    if verdict is None or verdict["status"] != status:
        return None
    return verdict


def _verified_verdict(
    required: object,
    satisfied: object,
    missing: object,
) -> dict[str, object] | None:
    if (
        not isinstance(required, int)
        or isinstance(required, bool)
        or not isinstance(satisfied, int)
        or isinstance(satisfied, bool)
        or not isinstance(missing, int)
        or isinstance(missing, bool)
        or required < 0
        or satisfied < 0
        or missing < 0
    ):
        return None
    if required != satisfied + missing:
        return None
    status = "complete" if missing == 0 else ("partial" if satisfied > 0 else "missing")
    return {
        "status": status,
        "required_count": required,
        "satisfied_count": satisfied,
        "missing_count": missing,
        "message": _verdict_message(status),
    }


def _verdict_message(status: str) -> str:
    if status == "complete":
        return "Required evidence coverage is satisfied."
    if status == "partial":
        return (
            "Required evidence coverage is partially satisfied; the task cannot "
            "complete without the remaining trusted evidence."
        )
    return (
        "Required evidence coverage is not satisfied; the task cannot "
        "complete without trusted evidence."
    )
