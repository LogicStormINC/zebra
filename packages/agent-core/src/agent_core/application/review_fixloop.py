"""Bounded Implementer→Tester→Reviewer fix loop (ORCH-REVIEW-FIXLOOP-01).

The loop reuses the worktree diff binding, reviewer verdicts and the
merge-gate decision. Iterations are bounded — after MAX_ITERATIONS the
loop settles as exceeded instead of cycling forever, and every move is an
explicit, legal transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_core.application.completion_gate import ReviewerVerdict
from agent_core.domain.worktree_orchestration import (
    MergeGateDecision,
    WorktreeDiffArtifact,
    WorktreeOwnership,
    WorktreeOwnershipError,
)

DEFAULT_MAX_ITERATIONS = 3


class FixLoopPhase(StrEnum):
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    HUMAN_REVIEW = "human_review"
    MERGE_GATE = "merge_gate"
    APPROVED = "approved"
    REJECTED = "rejected"
    LOOP_LIMIT_EXCEEDED = "loop_limit_exceeded"


TERMINAL_PHASES = frozenset(
    {
        FixLoopPhase.APPROVED,
        FixLoopPhase.REJECTED,
        FixLoopPhase.LOOP_LIMIT_EXCEEDED,
    }
)


class FixLoopTransitionError(ValueError):
    """Illegal phase move or bounded-loop violation."""


@dataclass(frozen=True)
class FixLoopMachine:
    """One bounded fix loop over a single worktree."""

    ownership: WorktreeOwnership
    phase: FixLoopPhase = FixLoopPhase.IMPLEMENTING
    iterations: int = 0
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    current_diff: WorktreeDiffArtifact | None = None

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise FixLoopTransitionError("max_iterations must be positive")
        if self.iterations > self.max_iterations:
            raise FixLoopTransitionError("iteration count exceeds the bound")

    # -- transitions -------------------------------------------------------

    def on_implementation_complete(self, diff: WorktreeDiffArtifact) -> FixLoopMachine:
        self._require(FixLoopPhase.IMPLEMENTING)
        try:
            bound = diff.bind(self.ownership)
        except WorktreeOwnershipError as exc:
            raise FixLoopTransitionError(str(exc)) from exc
        return FixLoopMachine(
            ownership=self.ownership,
            phase=FixLoopPhase.TESTING,
            iterations=self.iterations + 1,
            max_iterations=self.max_iterations,
            current_diff=bound,
        )

    def on_tests_complete(self, passed: bool) -> FixLoopMachine:
        self._require(FixLoopPhase.TESTING)
        if self.iterations > self.max_iterations:
            return self._terminal(FixLoopPhase.LOOP_LIMIT_EXCEEDED)
        if passed:
            return self._advance(FixLoopPhase.REVIEWING)
        return self._on_failure("tests_failed")

    def on_review(self, verdict: ReviewerVerdict) -> FixLoopMachine:
        self._require(FixLoopPhase.REVIEWING)
        if verdict.decision == "pass":
            return self._advance(FixLoopPhase.MERGE_GATE)
        if verdict.decision == "needs_human":
            return self._advance(FixLoopPhase.HUMAN_REVIEW)
        return self._on_failure("reviewer_rejected")

    def on_human_decision(self, approved: bool) -> FixLoopMachine:
        self._require(FixLoopPhase.HUMAN_REVIEW)
        if approved:
            return self._advance(FixLoopPhase.MERGE_GATE)
        return self._terminal(FixLoopPhase.REJECTED)

    def on_merge_gate(self, decision: MergeGateDecision) -> FixLoopMachine:
        self._require(FixLoopPhase.MERGE_GATE)
        if decision.approved:
            return self._terminal(FixLoopPhase.APPROVED)
        if decision.reason_code == "merge_conflict":
            # conflicts are fixable: loop back with a fresh diff
            return self._on_failure("merge_conflict")
        return self._terminal(FixLoopPhase.REJECTED)

    # -- internals ---------------------------------------------------------

    def _require(self, phase: FixLoopPhase) -> None:
        if self.phase is not phase:
            raise FixLoopTransitionError(
                f"illegal fix-loop transition: expected {phase.value}, "
                f"machine is {self.phase.value}"
            )

    def _advance(self, phase: FixLoopPhase) -> FixLoopMachine:
        return FixLoopMachine(
            ownership=self.ownership,
            phase=phase,
            iterations=self.iterations,
            max_iterations=self.max_iterations,
            current_diff=self.current_diff,
        )

    def _terminal(self, phase: FixLoopPhase) -> FixLoopMachine:
        return self._advance(phase)

    def _on_failure(self, reason: str) -> FixLoopMachine:
        if self.iterations >= self.max_iterations:
            return self._terminal(FixLoopPhase.LOOP_LIMIT_EXCEEDED)
        # bounded restart: back to implementing with the diff cleared
        return FixLoopMachine(
            ownership=self.ownership,
            phase=FixLoopPhase.IMPLEMENTING,
            iterations=self.iterations,
            max_iterations=self.max_iterations,
            current_diff=None,
        )
