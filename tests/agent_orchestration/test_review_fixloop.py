"""Fix-loop tests: phases, bounds, verdicts, ownership binding."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agent_core.domain.identifiers import TaskId
from agent_orchestration.application.completion_gate import ReviewerVerdict
from agent_orchestration.application.review_fixloop import (
    DEFAULT_MAX_ITERATIONS,
    FixLoopMachine,
    FixLoopPhase,
    FixLoopTransitionError,
)
from agent_orchestration.domain.worktree_orchestration import (
    MergeGateDecision,
    WorktreeDiffArtifact,
    WorktreeOwnership,
)


def _ownership() -> WorktreeOwnership:
    return WorktreeOwnership(
        worktree_id="wt-loop",
        child_task_id=TaskId(uuid4()),
        base_revision="abc123",
        branch_ref="refs/heads/zebra/wt-loop",
        owned_paths=("apps/api/",),
        workspace_quota_bytes=1_048_576,
        runtime_spec_digest="d" * 64,
    )


def _diff(paths: tuple[str, ...] = ("apps/api/main.py",)) -> WorktreeDiffArtifact:
    return WorktreeDiffArtifact(
        worktree_id="wt-loop",
        diff_digest="e" * 64,
        changed_paths=paths,
        artifact_uri="artifact://diffs/wt-loop",
    )


def _pass_verdict() -> ReviewerVerdict:
    return ReviewerVerdict(decision="pass", findings_count=0, confidence=0.9)


def _fail_verdict() -> ReviewerVerdict:
    return ReviewerVerdict(decision="fail", findings_count=2, confidence=0.7)


def _gate(approved: bool, reason: str = "merge_approved") -> MergeGateDecision:
    return MergeGateDecision(approved=approved, reason_code=reason)  # noqa: B008


class TestHappyPath:
    def test_implement_test_review_merge_approve(self) -> None:
        machine = FixLoopMachine(ownership=_ownership())
        machine = machine.on_implementation_complete(_diff())
        assert machine.phase is FixLoopPhase.TESTING
        machine = machine.on_tests_complete(True)
        assert machine.phase is FixLoopPhase.REVIEWING
        machine = machine.on_review(_pass_verdict())
        assert machine.phase is FixLoopPhase.MERGE_GATE
        machine = machine.on_merge_gate(_gate(True))
        assert machine.phase is FixLoopPhase.APPROVED
        assert machine.iterations == 1


class TestBoundedLoop:
    def test_test_failures_restart_until_the_bound(self) -> None:
        machine = FixLoopMachine(ownership=_ownership(), max_iterations=2)
        machine = machine.on_implementation_complete(_diff())
        machine = machine.on_tests_complete(False)
        assert machine.phase is FixLoopPhase.IMPLEMENTING
        machine = machine.on_implementation_complete(_diff())
        machine = machine.on_tests_complete(False)
        assert machine.phase is FixLoopPhase.LOOP_LIMIT_EXCEEDED

    def test_reviewer_failures_consume_the_bound(self) -> None:
        machine = FixLoopMachine(ownership=_ownership(), max_iterations=1)
        machine = machine.on_implementation_complete(_diff())
        machine = machine.on_tests_complete(True)
        machine = machine.on_review(_fail_verdict())
        assert machine.phase is FixLoopPhase.LOOP_LIMIT_EXCEEDED

    def test_default_bound_is_three(self) -> None:
        assert DEFAULT_MAX_ITERATIONS == 3


class TestHumanReview:
    def test_needs_human_blocks_until_decision(self) -> None:
        machine = FixLoopMachine(ownership=_ownership())
        machine = machine.on_implementation_complete(_diff())
        machine = machine.on_tests_complete(True)
        machine = machine.on_review(
            ReviewerVerdict(decision="needs_human", findings_count=1, confidence=0.5)
        )
        assert machine.phase is FixLoopPhase.HUMAN_REVIEW
        approved = machine.on_human_decision(True)
        assert approved.phase is FixLoopPhase.MERGE_GATE
        rejected = machine.on_human_decision(False)
        assert rejected.phase is FixLoopPhase.REJECTED


class TestMergeGateBranch:
    def test_merge_conflict_loops_back(self) -> None:
        machine = FixLoopMachine(ownership=_ownership(), max_iterations=2)
        machine = machine.on_implementation_complete(_diff())
        machine = machine.on_tests_complete(True)
        machine = machine.on_review(_pass_verdict())
        machine = machine.on_merge_gate(_gate(False, reason="merge_conflict"))
        assert machine.phase is FixLoopPhase.IMPLEMENTING

    def test_other_merge_failures_reject(self) -> None:
        machine = FixLoopMachine(ownership=_ownership())
        machine = machine.on_implementation_complete(_diff())
        machine = machine.on_tests_complete(True)
        machine = machine.on_review(_pass_verdict())
        machine = machine.on_merge_gate(_gate(False, reason="tests_failed"))
        assert machine.phase is FixLoopPhase.REJECTED


class TestGuards:
    def test_diff_outside_ownership_rejected(self) -> None:
        machine = FixLoopMachine(ownership=_ownership())
        with pytest.raises(FixLoopTransitionError, match="outside ownership"):
            machine.on_implementation_complete(_diff(paths=("apps/worker/x.py",)))

    def test_illegal_transitions_rejected(self) -> None:
        machine = FixLoopMachine(ownership=_ownership())
        with pytest.raises(FixLoopTransitionError, match="illegal"):
            machine.on_tests_complete(True)
        reviewing = (
            FixLoopMachine(ownership=_ownership())
            .on_implementation_complete(_diff())
            .on_tests_complete(True)
        )
        with pytest.raises(FixLoopTransitionError, match="illegal"):
            reviewing.on_merge_gate(_gate(True))

    def test_terminal_phases_accept_nothing(self) -> None:
        approved = (
            FixLoopMachine(ownership=_ownership())
            .on_implementation_complete(_diff())
            .on_tests_complete(True)
            .on_review(_pass_verdict())
            .on_merge_gate(_gate(True))
        )
        with pytest.raises(FixLoopTransitionError):
            approved.on_tests_complete(True)
