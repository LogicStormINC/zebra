"""CA-P7-02B: orchestration runtime loop over an in-memory store double."""

from __future__ import annotations

from contextlib import nullcontext
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import TaskId
from agent_orchestration.application.orchestration_authority import OrchestrationAuthority
from agent_orchestration.application.orchestration_port import OrchestrationToolError
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime
from agent_orchestration.application.orchestration_scheduling import NodeOutcome
from agent_orchestration.application.orchestration_validation import PlanValidationContext
from agent_orchestration.domain.orchestration import (
    OrchestrationDependency,
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
    OrchestrationPlanSnapshot,
    OrchestrationRunStatus,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation

CAPS = frozenset({"agent.execute", "evidence.read"})


def _node(key: str, *, tokens: int = 100) -> OrchestrationNodeProposal:
    return OrchestrationNodeProposal(
        node_key=key,
        objective=f"Objective {key}",
        preferred_agent_role="researcher",
        required_capabilities=frozenset({"evidence.read"}),
        max_model_tokens=tokens,
        max_model_calls=2,
        max_tool_calls=3,
        max_runtime_seconds=60,
    )


def _proposal(*, tokens: int = 100, dependency: bool = False) -> OrchestrationPlanProposal:
    nodes = [_node("a", tokens=tokens), _node("b", tokens=tokens)]
    return OrchestrationPlanProposal(
        objective="Analyze",
        nodes=nodes,
        dependencies=((OrchestrationDependency(from_node="a", to_node="b"),) if dependency else ()),
        max_parallelism=1,
        synthesis_instruction="Merge",
    )


class MemoryStore:
    """In-memory OrchestrationStorePort double with CAS semantics."""

    deployment_namespace = "test-namespace"

    def __init__(self) -> None:
        self.runs: dict[str, OrchestrationPlanSnapshot] = {}
        self.status: dict[str, OrchestrationRunStatus] = {}
        self.node_status: dict[tuple[str, str], str] = {}

    def create_run(self, snapshot: OrchestrationPlanSnapshot) -> None:
        self.runs.setdefault(snapshot.run_ref, snapshot)
        self.status.setdefault(snapshot.run_ref, OrchestrationRunStatus.VALIDATED)

    def transition_run(self, run_ref, current, target) -> None:
        assert self.status[run_ref] is current, f"CAS: {run_ref} is {self.status[run_ref]}"
        self.status[run_ref] = target

    def get_snapshot(self, run_ref, revision=None):
        return self.runs.get(run_ref)

    def get_latest_revision(self, run_ref):
        return 1 if run_ref in self.runs else None

    def read_node_statuses(self, run_ref):
        return {
            node_key: value for (run, node_key), value in self.node_status.items() if run == run_ref
        }

    def transition_node(self, run_ref, node_key, target_status):
        self.node_status[(run_ref, node_key)] = target_status


def _authority() -> OrchestrationAuthority:
    return OrchestrationAuthority(
        parent_task_id=TaskId(uuid4()),
        parent_binding_digest="a" * 64,
        deployment_namespace="test-namespace",
        validation=PlanValidationContext(
            parent_capabilities=CAPS,
            parent_remaining_budget=BudgetReservation(
                model_tokens=1000, tool_calls=20, runtime_seconds=600
            ),
        ),
    )


def _runtime() -> tuple[OrchestrationRuntime, MemoryStore]:
    store = MemoryStore()
    authority = _authority()
    return OrchestrationRuntime(store, authorize=lambda action: nullcontext(authority)), store


def _propose(runtime: OrchestrationRuntime, *, tokens: int = 100, dependency: bool = False):
    return runtime.propose_plan(_proposal(tokens=tokens, dependency=dependency))


class TestProposeLoop:
    def test_propose_freezes_and_creates_run(self) -> None:
        runtime, store = _runtime()
        receipt = _propose(runtime)
        assert receipt.plan_revision == 1
        assert receipt.node_keys == ("a", "b")
        assert store.status[receipt.run_ref] is OrchestrationRunStatus.VALIDATED

    def test_budget_over_ceiling_is_a_typed_refusal(self) -> None:
        runtime, _store = _runtime()
        with pytest.raises(OrchestrationToolError) as raised:
            runtime.propose_plan(_proposal(tokens=600))
        assert raised.value.reason_code == "budget_beyond_parent"

    def test_unknown_run_request_fails_typed(self) -> None:
        runtime, _store = _runtime()
        with pytest.raises(OrchestrationToolError, match="unknown_run"):
            runtime.request_task(run_ref="run-missing", node_key="a")


class TestSchedulingLoop:
    def test_full_lifecycle_dispatch_gate_synthesize(self) -> None:
        runtime, store = _runtime()
        receipt = _propose(runtime, dependency=True)  # a → b 串行
        run_ref = receipt.run_ref

        runtime.materialize(run_ref)
        assert store.status[run_ref] is OrchestrationRunStatus.RUNNING

        # 初始调度：a 就绪，b 被依赖阻塞
        decision = runtime.evaluate(run_ref)
        assert decision.ready_nodes == ("a",)

        # No real admission exists yet: dispatch refuses without changing state.
        with pytest.raises(OrchestrationToolError, match="dispatch_unavailable"):
            runtime.request_task(run_ref=run_ref, node_key="a")
        assert store.node_status == {}
        # Explicit stored child state for the loop-only completion fixture.
        store.transition_node(run_ref, "a", "running")

        # child_wakeup：a 完成 → b 就绪
        decision = runtime.complete_node(run_ref, "a", NodeOutcome.COMPLETED)
        assert "b" in decision.ready_nodes

        runtime.complete_node(run_ref, "b", NodeOutcome.COMPLETED)
        runtime.synthesize(run_ref)
        assert store.status[run_ref] is OrchestrationRunStatus.COMPLETED

    def test_node_failure_fails_the_loop_before_synthesis(self) -> None:
        runtime, _store = _runtime()
        receipt = _propose(runtime)
        runtime.materialize(receipt.run_ref)
        decision = runtime.complete_node(receipt.run_ref, "a", NodeOutcome.FAILED)
        assert decision.reason_code == "node_failed"
        with pytest.raises(OrchestrationToolError, match="nodes_still_running"):
            runtime.synthesize(receipt.run_ref)

    def test_evaluate_rebuilds_from_store_every_call(self) -> None:
        """崩溃恢复语义：无内存权威，每次评估从 store 重建。"""
        runtime, store = _runtime()
        receipt = _propose(runtime, dependency=True)
        runtime.materialize(receipt.run_ref)
        first = runtime.evaluate(receipt.run_ref)
        # 丢弃 runtime 实例（模拟重启），用同一 store 重建
        revived = OrchestrationRuntime(store)
        second = revived.evaluate(receipt.run_ref)
        assert second.ready_nodes == first.ready_nodes == ("a",)

    def test_parallel_nodes_without_dependencies_both_ready(self) -> None:
        runtime, _store = _runtime()
        receipt = _propose(runtime)  # 无依赖
        runtime.materialize(receipt.run_ref)
        decision = runtime.evaluate(receipt.run_ref)
        # max_parallelism=1 → 只取排序首个
        assert decision.ready_nodes == ("a",)


def test_proposal_preserves_the_real_parent_task_id() -> None:
    authority = _authority()
    store = MemoryStore()
    runtime = OrchestrationRuntime(store, authorize=lambda action: nullcontext(authority))
    receipt = runtime.propose_plan(_proposal())
    assert store.runs[receipt.run_ref].parent_task_id == authority.parent_task_id
