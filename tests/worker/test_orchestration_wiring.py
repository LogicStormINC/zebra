"""CA-P7-02B/C production wiring: hook mapping, gate refusal, view payload."""

from __future__ import annotations

from uuid import uuid4

from agent_orchestration.application.completion_gate import GateInput
from agent_orchestration.application.orchestration_port import OrchestrationToolError
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime
from agent_orchestration.application.orchestration_scheduling import NodeOutcome
from zebra_agent_worker.orchestration_wakeup_hook import outcome_for_child_status


def test_child_status_maps_onto_node_outcomes() -> None:
    assert outcome_for_child_status("completed") is NodeOutcome.COMPLETED
    assert outcome_for_child_status("failed") is NodeOutcome.FAILED
    assert outcome_for_child_status("cancelled") is NodeOutcome.CANCELLED
    assert outcome_for_child_status("timed_out") is NodeOutcome.TIMED_OUT
    assert outcome_for_child_status("running") is None  # 非终态不进 hook


def _gate_input(**overrides: object) -> GateInput:
    payload: dict[str, object] = {
        "model_claimed_complete": True,
        "evidence_count": 1,
        "successful_tool_calls": 1,
        "binding_digest": "a" * 64,
        "expected_binding_digest": "a" * 64,
    }
    payload.update(overrides)
    return GateInput.model_validate(payload)


class _MemoryStore:
    """In-memory OrchestrationStorePort double (runtime tests pattern)."""

    def __init__(self) -> None:

        self.runs: dict[str, object] = {}
        self.status: dict[str, object] = {}
        self.node_status: dict[tuple[str, str], str] = {}

    def create_run(self, snapshot) -> None:
        from agent_orchestration.domain.orchestration import OrchestrationRunStatus

        self.runs.setdefault(snapshot.run_ref, snapshot)
        self.status.setdefault(snapshot.run_ref, OrchestrationRunStatus.VALIDATED)

    def transition_run(self, run_ref, current, target) -> None:
        self.status[run_ref] = target

    def get_snapshot(self, run_ref, revision=None):
        return self.runs.get(run_ref)

    def get_latest_revision(self, run_ref):
        return 1 if run_ref in self.runs else None

    def read_node_statuses(self, run_ref):
        return {k: v for (r, k), v in self.node_status.items() if r == run_ref}

    def transition_node(self, run_ref, node_key, target_status) -> None:
        self.node_status[(run_ref, node_key)] = target_status


def _completed_two_node_run() -> tuple[OrchestrationRuntime, str, _MemoryStore]:
    from agent_orchestration.domain.orchestration import (
        OrchestrationNodeProposal,
        OrchestrationPlanProposal,
    )
    from agent_orchestration.domain.orchestration_budget import BudgetReservation

    store = _MemoryStore()
    runtime = OrchestrationRuntime(store)
    proposal = OrchestrationPlanProposal(
        objective="Analyze",
        nodes=(
            OrchestrationNodeProposal(
                node_key="a",
                objective="Objective a",
                preferred_agent_role="researcher",
                required_capabilities=frozenset({"evidence.read"}),
                max_model_tokens=100,
                max_model_calls=2,
                max_tool_calls=3,
                max_runtime_seconds=60,
            ),
            OrchestrationNodeProposal(
                node_key="b",
                objective="Objective b",
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
    )
    receipt = runtime.propose_plan(
        proposal,
        parent_task_id=str(uuid4()),
        parent_binding_digest="a" * 64,
        parent_remaining_budget=BudgetReservation(
            model_tokens=1000, tool_calls=20, runtime_seconds=600
        ),
        parent_capabilities=frozenset({"agent.execute", "evidence.read"}),
        write_capabilities=frozenset(),
    )
    runtime.materialize(receipt.run_ref)
    runtime.request_task(run_ref=receipt.run_ref, node_key="a")
    runtime.complete_node(receipt.run_ref, "a", NodeOutcome.COMPLETED)
    runtime.request_task(run_ref=receipt.run_ref, node_key="b")
    runtime.complete_node(receipt.run_ref, "b", NodeOutcome.COMPLETED)
    return runtime, receipt.run_ref, store


def test_gate_refusal_blocks_synthesis_with_typed_error() -> None:
    runtime, run_ref, _store = _completed_two_node_run()
    refusing = _gate_input(model_claimed_complete=False)
    try:
        runtime.synthesize(run_ref, gate_input=refusing)
        raise AssertionError("gate refusal must block synthesis")
    except OrchestrationToolError as error:
        assert error.reason_code == "gate_refused"


def test_passing_gate_allows_synthesis() -> None:
    from agent_orchestration.domain.orchestration import OrchestrationRunStatus

    runtime, run_ref, store = _completed_two_node_run()
    runtime.synthesize(run_ref, gate_input=_gate_input())
    assert store.status[run_ref] is OrchestrationRunStatus.COMPLETED


def test_task_view_payload_attaches_orchestration_when_store_present() -> None:
    from agent_core.domain.identifiers import TaskId
    from zebra_agent_api.ag_ui_task_view import task_view_payload

    class _Finder:
        def __init__(self, run_ref: str) -> None:
            self._run_ref = run_ref

        def find_run_for_parent(self, task_id):
            return self._run_ref

        def get_snapshot(self, run_ref, revision=None):
            return None  # view assembly tolerates absent snapshot

        def read_node_statuses(self, run_ref):
            return {}

        def read_run_status(self, run_ref):
            return "running"

    runtime, run_ref, store = _completed_two_node_run()
    finder = _Finder(run_ref)
    finder.get_snapshot = lambda run_ref, revision=None: store.runs.get(run_ref)  # type: ignore[method-assign]

    class _Stores:
        orchestration = finder

    payload = task_view_payload(_Stores(), TaskId(uuid4()))  # type: ignore[arg-type]
    assert payload["orchestration"]["runId"] == run_ref  # type: ignore[index]


def test_task_view_payload_without_orchestration_stays_minimal() -> None:
    from agent_core.domain.identifiers import TaskId
    from zebra_agent_api.ag_ui_task_view import task_view_payload

    class _Stores:
        orchestration = None

    payload = task_view_payload(_Stores(), TaskId(uuid4()))  # type: ignore[arg-type]
    assert "orchestration" not in payload  # type: ignore[index]
