"""CA-P7-02C: orchestration projection view assembly over the store surface."""

from __future__ import annotations

from contextlib import nullcontext

from agent_integrations.ag_ui.orchestration_state import orchestration_projection_view
from agent_orchestration.domain.orchestration import (
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
)

from tests.agent_orchestration.test_orchestration_runtime import MemoryStore, _authority


def _snapshot_store() -> MemoryStore:
    """Propose one run and mark a node running — a mid-flight store state."""

    from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime

    store = MemoryStore()
    authority = _authority()
    runtime = OrchestrationRuntime(store, authorize=lambda action: nullcontext(authority))
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
    )
    runtime.materialize(receipt.run_ref)
    # Projection fixture, not evidence of real child admission.
    store.transition_node(receipt.run_ref, "collect", "running")
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
