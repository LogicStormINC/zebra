"""Worktree ownership and merge gate tests (plan 9.2/9.3)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agent_core.domain.identifiers import TaskId
from agent_orchestration.domain.worktree_orchestration import (
    MergeGateInput,
    WorktreeDiffArtifact,
    WorktreeOwnership,
    WorktreeOwnershipError,
    assert_no_owned_path_conflicts,
    evaluate_merge_gate,
    worktree_fingerprint,
)
from pydantic import ValidationError

_FIXED_CHILD = TaskId(uuid4())


def _ownership(
    worktree_id: str = "wt-1",
    paths: tuple[str, ...] = ("apps/api/",),
    *,
    child: TaskId | None = None,
) -> WorktreeOwnership:
    return WorktreeOwnership(
        worktree_id=worktree_id,
        child_task_id=child or _FIXED_CHILD,
        base_revision="abc123",
        branch_ref=f"refs/heads/zebra/{worktree_id}",
        owned_paths=paths,
        workspace_quota_bytes=1_048_576,
        runtime_spec_digest="d" * 64,
    )


def _diff(
    paths: tuple[str, ...] = ("apps/api/main.py",),
    sensitive: tuple[str, ...] = (),
) -> WorktreeDiffArtifact:
    return WorktreeDiffArtifact(
        worktree_id="wt-1",
        diff_digest="e" * 64,
        changed_paths=paths,
        artifact_uri="artifact://diffs/wt-1",
        sensitive_paths=sensitive,
    )


class TestOwnership:
    def test_paths_normalize_and_sort(self) -> None:
        ownership = _ownership(paths=("b.py", "a.py"))
        assert ownership.owned_paths == ("/a.py", "/b.py")

    def test_owns_checks_prefix_semantics(self) -> None:
        ownership = _ownership(paths=("apps/api/",))
        assert ownership.owns("apps/api/main.py")
        assert ownership.owns("/apps/api/main.py")
        assert not ownership.owns("apps/worker/main.py")
        assert not ownership.owns("apps/api-other/file.py")

    def test_traversal_and_duplicates_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid"):
            _ownership(paths=("../etc/passwd",))
        with pytest.raises(ValidationError, match="unique"):
            _ownership(paths=("a.py", "a.py"))

    def test_conflicting_claims_fail_plan_time(self) -> None:
        first = _ownership(worktree_id="wt-a", paths=("apps/api/",))
        second = _ownership(worktree_id="wt-b", paths=("apps/api/routes.py",))
        with pytest.raises(WorktreeOwnershipError, match="conflict"):
            assert_no_owned_path_conflicts((first, second))

    def test_disjoint_claims_pass(self) -> None:
        first = _ownership(worktree_id="wt-a", paths=("apps/api/",))
        second = _ownership(worktree_id="wt-b", paths=("apps/worker/",))
        assert_no_owned_path_conflicts((first, second))

    def test_fingerprint_binds_ownership(self) -> None:
        base = _ownership()
        assert worktree_fingerprint(base) == worktree_fingerprint(_ownership())
        changed = _ownership(paths=("apps/api/", "apps/cli/"))
        assert worktree_fingerprint(base) != worktree_fingerprint(changed)


class TestDiffArtifact:
    def test_diff_must_stay_inside_ownership(self) -> None:
        ownership = _ownership()
        _diff(paths=("apps/api/main.py",)).bind(ownership)
        with pytest.raises(WorktreeOwnershipError, match="outside ownership"):
            _diff(paths=("apps/worker/main.py",)).bind(ownership)


class TestMergeGate:
    def test_all_clear_approves(self) -> None:
        decision = evaluate_merge_gate(MergeGateInput())
        assert decision.approved
        assert decision.reason_code == "merge_approved"

    def test_base_revision_drift_fails_closed(self) -> None:
        decision = evaluate_merge_gate(MergeGateInput(base_revision_current=False))
        assert not decision.approved
        assert decision.reason_code == "base_revision_drifted"

    def test_failed_tests_block_merge(self) -> None:
        decision = evaluate_merge_gate(MergeGateInput(tests_passed=False))
        assert decision.reason_code == "tests_failed"

    def test_failed_reviewer_blocks_merge(self) -> None:
        decision = evaluate_merge_gate(MergeGateInput(reviewer_passed=False))
        assert decision.reason_code == "reviewer_gate_failed"

    def test_sensitive_files_block_merge(self) -> None:
        decision = evaluate_merge_gate(
            MergeGateInput(sensitive_paths_present=(".env", "secrets.yaml"))
        )
        assert decision.reason_code == "sensitive_files_in_diff"

    def test_pending_effects_block_merge(self) -> None:
        decision = evaluate_merge_gate(MergeGateInput(pending_effects=2))
        assert decision.reason_code == "pending_effects"

    def test_conflicts_block_merge(self) -> None:
        decision = evaluate_merge_gate(MergeGateInput(conflicts=("apps/api/main.py",)))
        assert decision.reason_code == "merge_conflict"

    def test_pending_human_approval_blocks(self) -> None:
        decision = evaluate_merge_gate(
            MergeGateInput(human_approval_required=True, human_approved=None)
        )
        assert not decision.approved
        assert decision.reason_code == "human_approval_pending"

    def test_human_rejection_blocks(self) -> None:
        decision = evaluate_merge_gate(
            MergeGateInput(human_approval_required=True, human_approved=False)
        )
        assert decision.reason_code == "human_rejected_merge"

    def test_human_approval_unblocks(self) -> None:
        decision = evaluate_merge_gate(
            MergeGateInput(human_approval_required=True, human_approved=True)
        )
        assert decision.approved
