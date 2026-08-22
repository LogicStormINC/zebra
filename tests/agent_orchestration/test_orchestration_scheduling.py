"""Scheduler tests: readiness, policies, retry bounds, cancellation."""

from __future__ import annotations

import pytest
from agent_core.domain.agent_capabilities import capability_set
from agent_orchestration.application.orchestration_scheduling import (
    NodeOutcome,
    ScheduledNode,
    SchedulingState,
    cancel_run,
    on_node_terminal,
    select_ready,
)
from agent_orchestration.domain.orchestration import (
    OrchestrationDependency,
    OrchestrationNodeProposal,
    OrchestrationNodeStatus,
)


def _node(key: str, *, policy: str = "fail_plan") -> OrchestrationNodeProposal:
    return OrchestrationNodeProposal(
        node_key=key,
        objective=key,
        preferred_agent_role="researcher",
        required_capabilities=frozenset(capability_set(["evidence.read"])),
        max_model_tokens=100,
        max_model_calls=1,
        max_tool_calls=1,
        max_runtime_seconds=60,
        failure_policy=policy,  # type: ignore[arg-type]
    )


def _state(
    statuses: dict[str, OrchestrationNodeStatus],
    *,
    edges: tuple[tuple[str, str], ...] = (),
    policies: dict[str, str] | None = None,
) -> SchedulingState:
    policies = policies or {}
    nodes = {
        key: ScheduledNode(
            proposal=_node(key, policy=policies.get(key, "fail_plan")),
            status=status,
        )
        for key, status in statuses.items()
    }
    deps = tuple(
        OrchestrationDependency(from_node=a, to_node=b) for a, b in edges
    )
    return SchedulingState(nodes=nodes, dependencies=deps)  # type: ignore[arg-type]


class TestSelectReady:
    def test_blocked_nodes_with_settled_deps_become_ready(self) -> None:
        state = _state(
            {"a": OrchestrationNodeStatus.COMPLETED, "b": OrchestrationNodeStatus.BLOCKED},
            edges=(("a", "b"),),
        )
        assert select_ready(state, max_parallelism=2) == ("b",)

    def test_unsettled_deps_stay_blocked(self) -> None:
        state = _state(
            {"a": OrchestrationNodeStatus.RUNNING, "b": OrchestrationNodeStatus.BLOCKED},
            edges=(("a", "b"),),
        )
        assert select_ready(state, max_parallelism=2) == ()

    def test_parallelism_cap_limits_selection(self) -> None:
        state = _state(
            {
                "a": OrchestrationNodeStatus.BLOCKED,
                "b": OrchestrationNodeStatus.BLOCKED,
                "c": OrchestrationNodeStatus.BLOCKED,
            }
        )
        assert select_ready(state, max_parallelism=2) == ("a", "b")
        running = _state(
            {
                "a": OrchestrationNodeStatus.RUNNING,
                "b": OrchestrationNodeStatus.RUNNING,
                "c": OrchestrationNodeStatus.BLOCKED,
            }
        )
        assert select_ready(running, max_parallelism=2) == ()


class TestFailurePolicies:
    def test_fail_plan_cancels_every_running_node(self) -> None:
        state = _state(
            {
                "a": OrchestrationNodeStatus.RUNNING,
                "b": OrchestrationNodeStatus.QUEUED,
                "c": OrchestrationNodeStatus.COMPLETED,
            }
        )
        decision = on_node_terminal(state, "a", NodeOutcome.FAILED)
        assert decision.run_failed is True
        assert decision.reason_code == "node_failed_run_fails"
        assert ("b", OrchestrationNodeStatus.CANCELLED) in decision.node_updates
        assert all(key != "c" for key, _ in decision.node_updates)  # terminal untouched

    def test_continue_skips_transitive_dependents_only(self) -> None:
        state = _state(
            {
                "a": OrchestrationNodeStatus.RUNNING,
                "b": OrchestrationNodeStatus.BLOCKED,
                "c": OrchestrationNodeStatus.BLOCKED,
                "d": OrchestrationNodeStatus.BLOCKED,
            },
            edges=(("a", "b"), ("b", "c"), ("a", "d")),
            policies={"a": "continue"},
        )
        decision = on_node_terminal(state, "a", NodeOutcome.FAILED)
        assert decision.run_failed is False
        assert decision.reason_code == "failure_tolerated_dependents_skipped"
        updated = dict(decision.node_updates)
        assert updated["b"] is OrchestrationNodeStatus.SKIPPED
        assert updated["c"] is OrchestrationNodeStatus.SKIPPED
        assert updated["d"] is OrchestrationNodeStatus.SKIPPED

    def test_retry_once_requeues_within_bounds(self) -> None:
        state = _state(
            {"a": OrchestrationNodeStatus.RUNNING},
            policies={"a": "retry_once"},
        )
        decision = on_node_terminal(state, "a", NodeOutcome.TIMED_OUT)
        assert decision.retry_keys == ("a",)
        assert decision.node_updates == (("a", OrchestrationNodeStatus.QUEUED),)

    def test_retry_exhausted_falls_through_to_fail_plan(self) -> None:
        node = ScheduledNode(
            proposal=_node("a", policy="retry_once"),
            status=OrchestrationNodeStatus.RUNNING,
            attempts=1,
        )
        state = SchedulingState(nodes={"a": node})
        decision = on_node_terminal(state, "a", NodeOutcome.FAILED)
        assert decision.run_failed is True
        assert decision.reason_code == "node_failed_run_fails"

    def test_require_human_blocks_the_run(self) -> None:
        state = _state(
            {"a": OrchestrationNodeStatus.RUNNING},
            policies={"a": "require_human"},
        )
        decision = on_node_terminal(state, "a", NodeOutcome.FAILED)
        assert decision.run_blocked is True
        assert decision.node_updates == (
            ("a", OrchestrationNodeStatus.WAITING_APPROVAL),
        )
        assert decision.run_failed is False


class TestCancellation:
    def test_node_cancellation_fails_the_run_and_cancels_others(self) -> None:
        state = _state(
            {"a": OrchestrationNodeStatus.RUNNING, "b": OrchestrationNodeStatus.QUEUED}
        )
        decision = on_node_terminal(state, "a", NodeOutcome.CANCELLED)
        assert decision.run_failed is True
        assert ("b", OrchestrationNodeStatus.CANCELLED) in decision.node_updates

    def test_run_cancellation_reaches_every_non_terminal_node(self) -> None:
        state = _state(
            {
                "a": OrchestrationNodeStatus.COMPLETED,
                "b": OrchestrationNodeStatus.RUNNING,
                "c": OrchestrationNodeStatus.BLOCKED,
            }
        )
        decision = cancel_run(state)
        keys = [key for key, _ in decision.node_updates]
        assert keys == ["b", "c"]
        assert decision.reason_code == "run_cancelled"


class TestGuards:
    def test_unknown_node_rejected(self) -> None:
        state = _state({"a": OrchestrationNodeStatus.RUNNING})
        with pytest.raises(ValueError, match="unknown node"):
            on_node_terminal(state, "ghost", NodeOutcome.FAILED)
