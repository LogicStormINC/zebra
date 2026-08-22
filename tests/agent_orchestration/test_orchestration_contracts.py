"""Orchestration contract tests: proposals, snapshots, replans, states."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.identifiers import TaskId
from agent_orchestration.domain.orchestration import (
    RUN_TERMINAL_STATUSES,
    OrchestrationDependency,
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
    OrchestrationPlanSnapshot,
    OrchestrationRunStatus,
    assert_run_transition,
    snapshot_from_proposal,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation
from pydantic import ValidationError


def _node(key: str = "research-a") -> OrchestrationNodeProposal:
    return OrchestrationNodeProposal(
        node_key=key,
        objective="Gather evidence",
        preferred_agent_role="researcher",
        required_capabilities=frozenset(capability_set(["evidence.read"])),
        max_model_tokens=1000,
        max_model_calls=3,
        max_tool_calls=5,
        max_runtime_seconds=120,
    )


def _proposal(**overrides: object) -> OrchestrationPlanProposal:
    payload: dict[str, object] = {
        "objective": "Answer with evidence",
        "nodes": (_node(),),
        "dependencies": (),
        "max_parallelism": 1,
        "synthesis_instruction": "Merge findings",
    }
    payload.update(overrides)
    return OrchestrationPlanProposal(**payload)  # type: ignore[arg-type]


_FIXED_PARENT = TaskId(uuid4())


def _snapshot(proposal: OrchestrationPlanProposal) -> OrchestrationPlanSnapshot:
    return snapshot_from_proposal(
        proposal,
        run_ref="run-1",
        parent_task_id=_FIXED_PARENT,
        parent_binding_digest="a" * 64,
        reserved_budget=BudgetReservation(
            model_tokens=10_000, tool_calls=50, runtime_seconds=600
        ),
    )


class TestProposal:
    def test_duplicate_node_keys_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unique"):
            _proposal(nodes=(_node("a"), _node("a")))

    def test_dependency_on_unknown_node_rejected(self) -> None:
        edge = OrchestrationDependency(from_node="ghost", to_node="research-a")
        with pytest.raises(ValidationError, match="declared nodes"):
            _proposal(dependencies=(edge,))

    def test_self_dependency_rejected(self) -> None:
        with pytest.raises(ValidationError, match="itself"):
            OrchestrationDependency(from_node="a", to_node="a")

    def test_parallelism_cannot_exceed_nodes(self) -> None:
        with pytest.raises(ValidationError, match="parallelism"):
            _proposal(max_parallelism=2)

    def test_zero_budget_node_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-zero budget"):
            _proposal(
                nodes=(
                    _node().model_copy(
                        update={
                            "max_model_tokens": 0,
                            "max_model_calls": 0,
                            "max_tool_calls": 0,
                        }
                    ),
                )
            )


class TestSnapshot:
    def test_digest_is_deterministic_and_revision_scoped(self) -> None:
        proposal = _proposal(nodes=(_node("a"), _node("b")))
        first = _snapshot(proposal)
        second = _snapshot(proposal)
        assert first.plan_digest == second.plan_digest
        bumped = first.next_revision()
        assert bumped.plan_revision == 2
        assert bumped.plan_digest != first.plan_digest

    def test_child_materialization_changes_digest(self) -> None:
        snapshot = _snapshot(_proposal())
        materialized = snapshot.model_copy(
            update={
                "nodes": (
                    snapshot.nodes[0].model_copy(
                        update={"child_task_id": TaskId(uuid4())}
                    ),
                )
            }
        )
        assert materialized.plan_digest != snapshot.plan_digest


class TestReplan:
    def test_replan_appends_and_cancels_without_rewriting(self) -> None:
        snapshot = _snapshot(_proposal(nodes=(_node("a"), _node("b"))))
        revised = snapshot.next_revision(
            added_nodes=(_node("c"),),
            cancelled_node_keys=("b",),
        )
        assert {node.node_key for node in revised.nodes} == {"a", "c"}
        assert revised.plan_revision == 2

    def test_replan_cannot_redefine_existing_nodes(self) -> None:
        snapshot = _snapshot(_proposal())
        with pytest.raises(ValueError, match="redefine"):
            snapshot.next_revision(added_nodes=(_node("research-a"),))

    def test_replan_cannot_cancel_unknown_nodes(self) -> None:
        snapshot = _snapshot(_proposal())
        with pytest.raises(ValueError, match="unknown node"):
            snapshot.next_revision(cancelled_node_keys=("ghost",))

    def test_replan_cannot_empty_the_plan(self) -> None:
        snapshot = _snapshot(_proposal())
        with pytest.raises(ValueError, match="at least one node"):
            snapshot.next_revision(cancelled_node_keys=("research-a",))


class TestRunStateMachine:
    def test_happy_path_is_legal(self) -> None:
        path = (
            OrchestrationRunStatus.PROPOSED,
            OrchestrationRunStatus.VALIDATED,
            OrchestrationRunStatus.MATERIALIZING,
            OrchestrationRunStatus.RUNNING,
            OrchestrationRunStatus.WAITING,
            OrchestrationRunStatus.SYNTHESIZING,
            OrchestrationRunStatus.COMPLETED,
        )
        current = path[0]
        for target in path[1:]:
            current = assert_run_transition(current, target)

    def test_illegal_jump_rejected(self) -> None:
        with pytest.raises(ValueError, match="illegal"):
            assert_run_transition(
                OrchestrationRunStatus.PROPOSED,
                OrchestrationRunStatus.COMPLETED,
            )

    def test_terminal_states_are_final(self) -> None:
        from agent_orchestration.domain.orchestration import RUN_TRANSITIONS

        for terminal in RUN_TERMINAL_STATUSES:
            assert RUN_TRANSITIONS[terminal] == frozenset()
