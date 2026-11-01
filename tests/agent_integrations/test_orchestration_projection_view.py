"""CA-P7-02C: orchestration projection view assembly over the store surface."""

from __future__ import annotations

from uuid import uuid4

from agent_integrations.ag_ui.orchestration_state import orchestration_projection_view
from agent_orchestration.domain.orchestration import (
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation

from tests.agent_orchestration.test_orchestration_runtime import MemoryStore, _propose  # noqa: F401


def _snapshot_store() -> MemoryStore:
    """Propose one run and mark a node running — a mid-flight store state."""

    from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime

    store = MemoryStore()
    runtime = OrchestrationRuntime(store)
    receipt = runtime.propose_plan(
        OrchestrationPlanProposal(
            objective="Analyze",
            nodes=(
                OrchestrationNodeProposal(
                    node_key="collect",
                    objective="Collect",
                    preferred_agent_role="researcher",
                    required_capabilities=frozenset({"evidence.read"}),
                    max_model_tokens=100,
                    max_model_calls=2,
                    max_tool_calls=3,
                    max_runtime_seconds=60,
                ),
            ),
            dependencies=(),
            max_parallelism=1,
            synthesis_instruction="Merge",
        ),
        parent_task_id=str(uuid4()),
        parent_binding_digest="a" * 64,
        parent_remaining_budget=BudgetReservation(
            model_tokens=1000, tool_calls=20, runtime_seconds=600
        ),
        parent_capabilities=frozenset({"agent.execute", "evidence.read"}),
        write_capabilities=frozenset(),
    )
    runtime.materialize(receipt.run_ref)
    runtime.request_task(run_ref=receipt.run_ref, node_key="collect")
    store.read_run_status = lambda run_ref: store.status[run_ref].value  # type: ignore[method-assign]
    return store


class TestOrchestrationProjectionView:
    def test_mid_flight_run_projects_nodes_and_status(self) -> None:
        store = _snapshot_store()
        run_ref = next(iter(store.runs))
        view = orchestration_projection_view(store, run_ref)
        assert view is not None
        state = view["orchestration"]
        assert state["runId"] == run_ref
        assert state["status"] == "running"
        node = state["nodes"]["collect"]
        assert node["status"] == "running"
        assert node["role"] == "researcher"
        assert node["budget"]["modelTokensUsed"] == 0

    def test_unknown_run_returns_none(self) -> None:
        store = _snapshot_store()
        assert orchestration_projection_view(store, "run-missing") is None
