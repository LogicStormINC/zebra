"""Worker orchestration runtime: the single writer of orchestration run state (CA-P7-02B).

Implements OrchestrationRuntimePort for the Agent Layer tools and drives the
validate → create_run → schedule → dispatch → gate → synthesize loop. Storage
is injected as a protocol so the whole loop is testable without PostgreSQL;
the Postgres adapter lives in agent-storage. Scheduling state is rebuilt from
the store on every evaluation — crash recovery is "reload and re-decide",
never in-memory authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from agent_core.domain.identifiers import TaskId

from agent_orchestration.application.completion_gate import (
    GateInput,
    evaluate_gate,
)
from agent_orchestration.application.orchestration_port import (
    OrchestrationToolError,
    PlanProposalReceipt,
    TaskRequestReceipt,
)
from agent_orchestration.application.orchestration_scheduling import (
    NodeOutcome,
    ScheduledNode,
    SchedulingState,
    on_node_terminal,
    select_ready,
)
from agent_orchestration.application.orchestration_validation import (
    PlanValidationContext,
    PlanValidationError,
    validate_plan,
)
from agent_orchestration.domain.orchestration import (
    OrchestrationNodeStatus,
    OrchestrationPlanProposal,
    OrchestrationPlanSnapshot,
    OrchestrationRunStatus,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation


class OrchestrationStorePort(Protocol):
    """The store surface the runtime depends on (Postgres adapter exists)."""

    def create_run(self, snapshot: OrchestrationPlanSnapshot) -> None: ...

    def transition_run(
        self,
        run_ref: str,
        current: OrchestrationRunStatus,
        target: OrchestrationRunStatus,
    ) -> None: ...

    def get_snapshot(
        self, run_ref: str, revision: int | None = None
    ) -> OrchestrationPlanSnapshot | None: ...

    def get_latest_revision(self, run_ref: str) -> int | None: ...

    def read_node_statuses(self, run_ref: str) -> dict[str, str]: ...

    def transition_node(self, run_ref: str, node_key: str, target_status: str) -> None: ...


@dataclass(frozen=True)
class LoopDecision:
    """One scheduler evaluation over the rebuilt state."""

    run_ref: str
    ready_nodes: tuple[str, ...]
    run_complete: bool
    reason_code: str | None


def _plan_parallelism(snapshot: OrchestrationPlanSnapshot) -> int:
    """Snapshot 冻结了节点图但未存 parallelism；调度保守取节点数上限 1。"""
    return 1


_SCHEDULING_STATUS = {
    "blocked": OrchestrationNodeStatus.BLOCKED,
    "ready": OrchestrationNodeStatus.READY,
    "queued": OrchestrationNodeStatus.QUEUED,
    "running": OrchestrationNodeStatus.RUNNING,
    "waiting_approval": OrchestrationNodeStatus.WAITING_APPROVAL,
    "waiting_children": OrchestrationNodeStatus.WAITING_CHILDREN,
    "verifying": OrchestrationNodeStatus.VERIFYING,
    "completed": OrchestrationNodeStatus.COMPLETED,
    "failed": OrchestrationNodeStatus.FAILED,
    "cancelled": OrchestrationNodeStatus.CANCELLED,
    "skipped": OrchestrationNodeStatus.SKIPPED,
}


def _state_from_snapshot(
    snapshot: OrchestrationPlanSnapshot, statuses: dict[str, str]
) -> SchedulingState:
    nodes = {
        node.proposal.node_key: ScheduledNode(
            proposal=node.proposal,
            status=_SCHEDULING_STATUS.get(
                statuses.get(node.proposal.node_key, "blocked"),
                OrchestrationNodeStatus.BLOCKED,
            ),
        )
        for node in snapshot.nodes
    }
    return SchedulingState(nodes=nodes, dependencies=snapshot.dependencies)


class OrchestrationRuntime:
    """The port implementation plus the worker-side loop driver."""

    def __init__(self, store: OrchestrationStorePort) -> None:
        self._store = store

    # ------------------------------------------------------- port surface (02A)
    def propose_plan(
        self,
        proposal: OrchestrationPlanProposal,
        *,
        parent_task_id: str,
        parent_binding_digest: str,
        parent_remaining_budget: BudgetReservation,
        parent_capabilities: frozenset[str],
        write_capabilities: frozenset[str],
    ) -> PlanProposalReceipt:
        context = PlanValidationContext(
            parent_capabilities=frozenset(parent_capabilities),  # type: ignore[arg-type]
            parent_remaining_budget=parent_remaining_budget,
            write_capabilities=frozenset(write_capabilities),  # type: ignore[arg-type]
        )
        run_ref = f"run-{uuid4().hex[:12]}"
        try:
            snapshot = validate_plan(
                proposal,
                context,
                run_ref=run_ref,
                parent_task_id=TaskId(uuid4()),
                parent_binding_digest=parent_binding_digest,
            )
        except PlanValidationError as error:
            raise OrchestrationToolError(error.reason_code, error.detail) from None
        self._store.create_run(snapshot)
        return PlanProposalReceipt(
            run_ref=run_ref,
            plan_revision=snapshot.plan_revision,
            node_keys=tuple(node.proposal.node_key for node in snapshot.nodes),
            reserved_budget=snapshot.reserved_budget,
        )

    def request_task(self, *, run_ref: str, node_key: str) -> TaskRequestReceipt:
        snapshot = self._require_snapshot(run_ref)
        if node_key not in {node.proposal.node_key for node in snapshot.nodes}:
            raise OrchestrationToolError("unknown_node", f"{run_ref} has no node {node_key}")
        decision = self.evaluate(run_ref)
        if node_key not in decision.ready_nodes:
            raise OrchestrationToolError(
                "node_not_ready",
                f"{node_key} is not dispatchable (dependencies or parallelism cap)",
            )
        self._store.transition_node(run_ref, node_key, "running")
        return TaskRequestReceipt(
            run_ref=run_ref,
            node_key=node_key,
            child_task_id=str(uuid4()),
        )

    # ---------------------------------------------------- loop driver (02B)
    def materialize(self, run_ref: str) -> None:
        """validated → materializing → running, CAS-guarded by the store."""

        self._store.transition_run(
            run_ref, OrchestrationRunStatus.VALIDATED, OrchestrationRunStatus.MATERIALIZING
        )
        self._store.transition_run(
            run_ref, OrchestrationRunStatus.MATERIALIZING, OrchestrationRunStatus.RUNNING
        )

    def evaluate(self, run_ref: str) -> LoopDecision:
        """Rebuild scheduling state from the store, then decide one step.

        Crash recovery is this method: nothing is cached, so a restarted
        worker re-decides from persisted facts.
        """

        snapshot = self._require_snapshot(run_ref)
        state = _state_from_snapshot(snapshot, self._store.read_node_statuses(run_ref))
        ready = select_ready(state, max_parallelism=_plan_parallelism(snapshot))
        all_terminal = all(node.terminal for node in state.nodes.values())
        return LoopDecision(
            run_ref=run_ref,
            ready_nodes=ready,
            run_complete=all_terminal,
            reason_code=None if ready or all_terminal else "blocked_on_dependencies",
        )

    def complete_node(
        self,
        run_ref: str,
        node_key: str,
        outcome: NodeOutcome,
    ) -> LoopDecision:
        """One child terminal report; then re-evaluate (child_wakeup hook)."""

        snapshot = self._require_snapshot(run_ref)
        state = _state_from_snapshot(snapshot, self._store.read_node_statuses(run_ref))
        decision = on_node_terminal(state, node_key, outcome)
        terminal_status = "completed" if outcome is NodeOutcome.COMPLETED else outcome.value
        self._store.transition_node(run_ref, node_key, terminal_status)
        if decision.run_failed:
            return LoopDecision(
                run_ref=run_ref,
                ready_nodes=(),
                run_complete=False,
                reason_code="node_failed",
            )
        return self.evaluate(run_ref)

    def synthesize(
        self,
        run_ref: str,
        *,
        gate_input: GateInput | None = None,
    ) -> None:
        """running → synthesizing → completed once every node is terminal.

        CA-P7-02B wiring: a supplied GateInput is evaluated by the
        completion gate BEFORE the synthesizing transition — a failing or
        blocking gate refuses synthesis with a typed error and the run
        stays running. Without a gate input the terminal check alone
        decides (unit/test surface).
        """

        snapshot = self._require_snapshot(run_ref)
        state = _state_from_snapshot(snapshot, self._store.read_node_statuses(run_ref))
        if not all(node.terminal for node in state.nodes.values()):
            raise OrchestrationToolError(
                "nodes_still_running", f"{run_ref} still has non-terminal nodes"
            )
        if gate_input is not None:
            evaluation = evaluate_gate(f"orchestration:{run_ref}", gate_input)
            if evaluation.blocked:
                raise OrchestrationToolError(
                    "gate_blocked", evaluation.reason_code
                )
            if not evaluation.passed:
                raise OrchestrationToolError(
                    "gate_refused", evaluation.reason_code
                )
        self._store.transition_run(
            run_ref, OrchestrationRunStatus.RUNNING, OrchestrationRunStatus.SYNTHESIZING
        )
        self._store.transition_run(
            run_ref, OrchestrationRunStatus.SYNTHESIZING, OrchestrationRunStatus.COMPLETED
        )

    def _require_snapshot(self, run_ref: str) -> OrchestrationPlanSnapshot:
        snapshot = self._store.get_snapshot(run_ref)
        if snapshot is None:
            raise OrchestrationToolError("unknown_run", f"no orchestration run {run_ref}")
        return snapshot
