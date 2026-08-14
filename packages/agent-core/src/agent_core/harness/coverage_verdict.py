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
    if (
        not isinstance(required, int)
        or isinstance(required, bool)
        or not isinstance(satisfied, int)
        or isinstance(satisfied, bool)
        or not isinstance(missing, int)
        or isinstance(missing, bool)
    ):
        return None
    if missing == 0:
        status = "complete"
        message = "Required evidence coverage is satisfied."
    elif satisfied > 0:
        status = "partial"
        message = (
            "Required evidence coverage is partially satisfied; the task cannot "
            "complete without the remaining trusted evidence."
        )
    else:
        status = "missing"
        message = (
            "Required evidence coverage is not satisfied; the task cannot "
            "complete without trusted evidence."
        )
    return {
        "status": status,
        "required_count": required,
        "satisfied_count": satisfied,
        "missing_count": missing,
        "message": message,
    }
