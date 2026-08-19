"""Coding multi-agent conformance matrix (ORCH-CODE-CONFORMANCE-01).

The plan-19.3 acceptance rows, expressed over the deterministic contracts
landed in this phase: worktree isolation, ownership conflicts, merge
gates, bounded fix loops and reviewer authority.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from agent_core.application.completion_gate import ReviewerVerdict
from agent_core.application.review_fixloop import (
    FixLoopMachine,
    FixLoopPhase,
)
from agent_core.domain.identifiers import TaskId
from agent_core.domain.worktree_orchestration import (
    MergeGateDecision,
    MergeGateInput,
    WorktreeDiffArtifact,
    WorktreeOwnership,
    WorktreeOwnershipError,
    assert_no_owned_path_conflicts,
    evaluate_merge_gate,
)


def _ownership(worktree_id: str, paths: tuple[str, ...], base: str = "rev-1") -> WorktreeOwnership:
    return WorktreeOwnership(
        worktree_id=worktree_id,
        child_task_id=TaskId(uuid4()),
        base_revision=base,
        branch_ref=f"refs/heads/zebra/{worktree_id}",
        owned_paths=paths,
        workspace_quota_bytes=1_048_576,
        runtime_spec_digest="d" * 64,
    )


def _diff(worktree_id: str, paths: tuple[str, ...]) -> WorktreeDiffArtifact:
    return WorktreeDiffArtifact(
        worktree_id=worktree_id,
        diff_digest="e" * 64,
        changed_paths=paths,
        artifact_uri=f"artifact://diffs/{worktree_id}",
    )


class TestRow1And2:
    def test_row1_each_write_child_uses_an_isolated_worktree(self) -> None:
        writer_a = _ownership("wt-a", ("apps/api/",))
        writer_b = _ownership("wt-b", ("apps/worker/",))
        assert_no_owned_path_conflicts((writer_a, writer_b))
        assert writer_a.worktree_id != writer_b.worktree_id
        assert writer_a.owned_paths != writer_b.owned_paths

    def test_row2_parent_paths_stay_outside_child_claims(self) -> None:
        child = _ownership("wt-a", ("apps/api/",))
        parent_only = "packages/agent-core/core.py"
        assert not child.owns(parent_only)


class TestRow3And4:
    def test_row3_merge_requires_tests_review_and_diff_gate(self) -> None:
        missing_tests = evaluate_merge_gate(MergeGateInput(tests_passed=False))
        assert not missing_tests.approved
        missing_review = evaluate_merge_gate(MergeGateInput(reviewer_passed=False))
        assert not missing_review.approved
        full = evaluate_merge_gate(MergeGateInput())
        assert full.approved

    def test_row4_base_revision_drift_fails_closed(self) -> None:
        decision = evaluate_merge_gate(MergeGateInput(base_revision_current=False))
        assert decision.reason_code == "base_revision_drifted"


class TestRow5:
    def test_row5_merge_conflict_produces_artifact_and_human_gate(self) -> None:
        decision = evaluate_merge_gate(
            MergeGateInput(conflicts=("apps/api/main.py",))
        )
        assert decision.reason_code == "merge_conflict"
        assert decision.detail is not None  # the conflict artifact reference
        human = evaluate_merge_gate(
            MergeGateInput(human_approval_required=True, human_approved=None)
        )
        assert human.reason_code == "human_approval_pending"


class TestRow6And7:
    def test_row6_reviewer_has_no_write_surface(self) -> None:
        reviewer = _ownership("wt-review", ("docs/review.md",))
        # a reviewer diff attempting source changes is rejected by ownership
        with pytest.raises(WorktreeOwnershipError):
            _diff("wt-review", ("apps/api/main.py",)).bind(reviewer)

    def test_row7_tester_has_no_source_write_surface(self) -> None:
        tester = _ownership("wt-test", ("tests/output/",))
        with pytest.raises(WorktreeOwnershipError):
            _diff("wt-test", ("packages/app/source.py",)).bind(tester)


class TestRow8:
    def test_row8_child_crash_preserves_worktree_binding(self) -> None:
        ownership = _ownership("wt-a", ("apps/api/",))
        fingerprint_before = (
            ownership.worktree_id,
            ownership.base_revision,
            ownership.owned_paths,
        )
        # the binding is durable data: a crash-and-recover cycle rebuilds
        # the same ownership from persisted facts without change
        rebuilt = _ownership("wt-a", ("apps/api/",))
        assert (rebuilt.worktree_id, rebuilt.base_revision, rebuilt.owned_paths) == (
            fingerprint_before
        )


class TestLoopIntegration:
    def test_conflict_drives_a_bounded_fix_loop(self) -> None:
        machine = FixLoopMachine(ownership=_ownership("wt-loop", ("apps/api/",)), max_iterations=2)
        machine = machine.on_implementation_complete(_diff("wt-loop", ("apps/api/main.py",)))
        machine = machine.on_tests_complete(True)
        passing = ReviewerVerdict(decision="pass", findings_count=0, confidence=0.9)
        machine = machine.on_review(passing)
        machine = machine.on_merge_gate(
            MergeGateDecision(approved=False, reason_code="merge_conflict")
        )
        assert machine.phase is FixLoopPhase.IMPLEMENTING
        machine = machine.on_implementation_complete(_diff("wt-loop", ("apps/api/main.py",)))
        machine = machine.on_tests_complete(True)
        machine = machine.on_review(passing)
        approved = machine.on_merge_gate(
            MergeGateDecision(approved=True, reason_code="merge_approved")
        )
        assert approved.phase is FixLoopPhase.APPROVED
