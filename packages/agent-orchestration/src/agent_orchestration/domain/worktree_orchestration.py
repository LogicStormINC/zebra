"""Worktree ownership and merge gate (ORCH-WORKTREE-01, plan sections 9.2-9.3).

Write children own disjoint path sets inside isolated worktrees pinned to
a base revision. Merging is a Control Plane decision over deterministic
pre-checks — the Orchestrator Agent can only REQUEST a merge.
"""

from __future__ import annotations

import hashlib
import json
from typing import Self

from agent_core.domain.identifiers import TaskId
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_OWNED_PATHS = 64
MAX_PATH_LENGTH = 512


class WorktreeOwnershipError(ValueError):
    """Ownership declarations conflict or are malformed."""


class WorktreeOwnership(BaseModel):
    """One write child's exclusive path claim (plan 9.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worktree_id: str = Field(min_length=1, max_length=128)
    child_task_id: TaskId
    base_revision: str = Field(min_length=1, max_length=128)
    branch_ref: str = Field(min_length=1, max_length=256)
    owned_paths: tuple[str, ...] = Field(min_length=1, max_length=MAX_OWNED_PATHS)
    workspace_quota_bytes: int = Field(gt=0)
    runtime_spec_digest: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        normalized = tuple(
            path if path.startswith("/") else f"/{path}" for path in self.owned_paths
        )
        for path in normalized:
            if len(path) > MAX_PATH_LENGTH or ".." in path.split("/"):
                raise ValueError(f"owned path is invalid: {path}")
        if len(set(normalized)) != len(normalized):
            raise ValueError("owned paths must be unique")
        object.__setattr__(self, "owned_paths", tuple(sorted(normalized)))
        return self

    def owns(self, path: str) -> bool:
        normalized = path if path.startswith("/") else f"/{path}"
        return any(
            normalized == owned or normalized.startswith(owned.rstrip("/") + "/")
            for owned in self.owned_paths
        )


def assert_no_owned_path_conflicts(
    ownerships: tuple[WorktreeOwnership, ...],
) -> None:
    """Disjoint owned paths, enforced at plan time (plan 9.2)."""

    claims: list[tuple[str, str]] = [
        (ownership.worktree_id, path)
        for ownership in ownerships
        for path in ownership.owned_paths
    ]
    for holder, path in claims:
        for other, other_path in claims:
            if other == holder:
                continue
            if path == other_path or other_path.startswith(path.rstrip("/") + "/"):
                raise WorktreeOwnershipError(
                    f"owned path conflict on {other_path}: {holder} vs {other}"
                )


class WorktreeDiffArtifact(BaseModel):
    """The durable diff record a write child publishes (plan 9.3 input)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worktree_id: str = Field(min_length=1, max_length=128)
    diff_digest: str = Field(min_length=64, max_length=64)
    changed_paths: tuple[str, ...] = Field(min_length=1, max_length=MAX_OWNED_PATHS)
    artifact_uri: str = Field(min_length=1, max_length=2048)
    sensitive_paths: tuple[str, ...] = ()

    def bind(self, ownership: WorktreeOwnership) -> WorktreeDiffArtifact:
        """Changed paths must stay inside the declared ownership."""

        for path in self.changed_paths:
            if not ownership.owns(path):
                raise WorktreeOwnershipError(
                    f"diff touches a path outside ownership: {path}"
                )
        return self


class MergeGateDecision(BaseModel):
    """Deterministic merge pre-check outcome (plan 9.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approved: bool
    reason_code: str = Field(min_length=1, max_length=128)
    detail: str | None = Field(default=None, max_length=512)


class MergeGateInput(BaseModel):
    """Durable facts for the merge pre-checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_revision_current: bool = True
    tests_passed: bool = True
    reviewer_passed: bool = True
    sensitive_paths_present: tuple[str, ...] = ()
    pending_effects: int = Field(ge=0, default=0)
    conflicts: tuple[str, ...] = ()
    human_approval_required: bool = False
    human_approved: bool | None = None


def evaluate_merge_gate(candidate: MergeGateInput) -> MergeGateDecision:
    """Plan 9.3 pre-checks, fail-closed with typed reasons."""

    if not candidate.base_revision_current:
        return MergeGateDecision(
            approved=False,
            reason_code="base_revision_drifted",
            detail="worktree base no longer matches the parent head",
        )
    if not candidate.tests_passed:
        return MergeGateDecision(approved=False, reason_code="tests_failed")
    if not candidate.reviewer_passed:
        return MergeGateDecision(approved=False, reason_code="reviewer_gate_failed")
    if candidate.sensitive_paths_present:
        return MergeGateDecision(
            approved=False,
            reason_code="sensitive_files_in_diff",
            detail=",".join(candidate.sensitive_paths_present[:8]),
        )
    if candidate.pending_effects:
        return MergeGateDecision(
            approved=False,
            reason_code="pending_effects",
            detail=f"count={candidate.pending_effects}",
        )
    if candidate.conflicts:
        return MergeGateDecision(
            approved=False,
            reason_code="merge_conflict",
            detail=",".join(candidate.conflicts[:8]),
        )
    if candidate.human_approval_required:
        if candidate.human_approved is None:
            return MergeGateDecision(
                approved=False,
                reason_code="human_approval_pending",
            )
        if not candidate.human_approved:
            return MergeGateDecision(approved=False, reason_code="human_rejected_merge")
    return MergeGateDecision(approved=True, reason_code="merge_approved")


def worktree_fingerprint(ownership: WorktreeOwnership) -> str:
    """Stable digest binding worktree identity to its ownership claims."""

    canonical = {
        "worktreeId": ownership.worktree_id,
        "childTaskId": str(ownership.child_task_id),
        "baseRevision": ownership.base_revision,
        "branchRef": ownership.branch_ref,
        "ownedPaths": list(ownership.owned_paths),
        "runtimeSpecDigest": ownership.runtime_spec_digest,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
