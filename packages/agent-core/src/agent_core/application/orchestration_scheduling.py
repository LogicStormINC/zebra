"""Pure-function DAG scheduler (ORCH-SCHEDULER-01).

Ready selection, failure-policy branching, bounded retry and cancel
propagation are deterministic over the node states and the frozen plan —
no timers, no I/O; the Control Plane owns durability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from agent_core.domain.orchestration import (
    NODE_TERMINAL_STATUSES,
    OrchestrationDependency,
    OrchestrationNodeProposal,
    OrchestrationNodeStatus,
)

MAX_RETRIES = 1


class NodeOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ScheduledNode:
    """Runtime facts for one node under the scheduler."""

    proposal: OrchestrationNodeProposal
    status: OrchestrationNodeStatus = OrchestrationNodeStatus.BLOCKED
    attempts: int = 0

    @property
    def node_key(self) -> str:
        return self.proposal.node_key

    @property
    def terminal(self) -> bool:
        return self.status in NODE_TERMINAL_STATUSES


@dataclass(frozen=True)
class SchedulingState:
    """Immutable snapshot of the schedulable graph."""

    nodes: dict[str, ScheduledNode] = field(default_factory=dict)
    dependencies: tuple[OrchestrationDependency, ...] = ()

    def with_status(
        self,
        node_key: str,
        status: OrchestrationNodeStatus,
        *,
        attempts: int | None = None,
    ) -> SchedulingState:
        node = self.nodes[node_key]
        updated = ScheduledNode(
            proposal=node.proposal,
            status=status,
            attempts=node.attempts if attempts is None else attempts,
        )
        return SchedulingState(
            nodes={**self.nodes, node_key: updated},
            dependencies=self.dependencies,
        )


@dataclass(frozen=True)
class SchedulingDecision:
    """Deterministic scheduler output for one evaluation."""

    node_updates: tuple[tuple[str, OrchestrationNodeStatus], ...] = ()
    retry_keys: tuple[str, ...] = ()
    run_failed: bool = False
    run_blocked: bool = False
    reason_code: str | None = None


def _dependencies_of(
    dependencies: tuple[OrchestrationDependency, ...],
    node_key: str,
) -> tuple[str, ...]:
    return tuple(edge.from_node for edge in dependencies if edge.to_node == node_key)


def _dependents_of(
    dependencies: tuple[OrchestrationDependency, ...],
    node_key: str,
) -> tuple[str, ...]:
    return tuple(edge.to_node for edge in dependencies if edge.from_node == node_key)


def _deps_settled(
    state: SchedulingState,
    node_key: str,
) -> bool:
    for parent in _dependencies_of(state.dependencies, node_key):
        node = state.nodes.get(parent)
        if node is None or node.status not in {
            OrchestrationNodeStatus.COMPLETED,
            OrchestrationNodeStatus.SKIPPED,
        }:
            return False
    return True


def select_ready(
    state: SchedulingState,
    *,
    max_parallelism: int,
) -> tuple[str, ...]:
    """BLOCKED nodes with settled dependencies, capped by in-flight slots."""

    in_flight = sum(
        1
        for node in state.nodes.values()
        if node.status
            in {
                OrchestrationNodeStatus.READY,
                OrchestrationNodeStatus.QUEUED,
                OrchestrationNodeStatus.RUNNING,
                OrchestrationNodeStatus.WAITING_APPROVAL,
                OrchestrationNodeStatus.WAITING_CHILDREN,
                OrchestrationNodeStatus.VERIFYING,
            }
    )
    slots = max(0, max_parallelism - in_flight)
    ready = [
        node.node_key
        for node in state.nodes.values()
        if node.status is OrchestrationNodeStatus.BLOCKED
        and _deps_settled(state, node.node_key)
    ]
    return tuple(sorted(ready)[:slots])


def on_node_terminal(
    state: SchedulingState,
    node_key: str,
    outcome: NodeOutcome,
) -> SchedulingDecision:
    """Apply failure policies, retries and dependency fallout."""

    node = state.nodes.get(node_key)
    if node is None:
        raise ValueError(f"unknown node {node_key}")
    if outcome is NodeOutcome.COMPLETED:
        return SchedulingDecision(reason_code="node_completed")

    cancelled = {
        key: value
        for key, value in state.nodes.items()
        if not value.terminal and key != node_key
    }

    if outcome is NodeOutcome.CANCELLED:
        updates = tuple(
            (key, OrchestrationNodeStatus.CANCELLED)
            for key in sorted(cancelled)
            if key != node_key
        )
        return SchedulingDecision(
            node_updates=updates,
            run_failed=True,
            reason_code="node_cancelled_run_fails",
        )

    # failed or timed_out: apply the node's failure policy
    policy = node.proposal.failure_policy
    if policy == "retry_once" and node.attempts <= MAX_RETRIES - 1:
        return SchedulingDecision(
            node_updates=((node_key, OrchestrationNodeStatus.QUEUED),),
            retry_keys=(node_key,),
            reason_code="bounded_retry_scheduled",
        )
    if policy == "continue":
        skipped = tuple(
            (key, OrchestrationNodeStatus.SKIPPED)
            for key in sorted(_transitive_dependents(state, node_key))
            if not state.nodes[key].terminal
        )
        return SchedulingDecision(
            node_updates=skipped,
            reason_code="failure_tolerated_dependents_skipped",
        )
    if policy == "require_human":
        return SchedulingDecision(
            node_updates=((node_key, OrchestrationNodeStatus.WAITING_APPROVAL),),
            run_blocked=True,
            reason_code="human_approval_required",
        )
    # fail_plan (default)
    updates = tuple(
        (key, OrchestrationNodeStatus.CANCELLED)
        for key in sorted(cancelled)
    )
    return SchedulingDecision(
        node_updates=updates,
        run_failed=True,
        reason_code="node_failed_run_fails",
    )


def cancel_run(state: SchedulingState) -> SchedulingDecision:
    """Cancel every non-terminal node (propagation from the run level)."""

    updates = tuple(
        (key, OrchestrationNodeStatus.CANCELLED)
        for key, node in sorted(state.nodes.items())
        if not node.terminal
    )
    return SchedulingDecision(
        node_updates=updates,
        run_failed=True,
        reason_code="run_cancelled",
    )


def _transitive_dependents(
    state: SchedulingState,
    node_key: str,
) -> set[str]:
    seen: set[str] = set()
    frontier = [node_key]
    while frontier:
        current = frontier.pop()
        for child in _dependents_of(state.dependencies, current):
            if child not in seen:
                seen.add(child)
                frontier.append(child)
    return seen
