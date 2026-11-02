"""Worker orchestration runtime: the single writer of orchestration run state (CA-P7-02B).

Implements OrchestrationRuntimePort for the Agent Layer tools and drives the
validate → create_run → schedule → dispatch → gate → synthesize loop. Storage
is injected as a protocol so the whole loop is testable without PostgreSQL;
the Postgres adapter lives in agent-storage. Scheduling state is rebuilt from
the store on every evaluation — crash recovery is "reload and re-decide",
never in-memory authority.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from agent_orchestration.application.completion_gate import (
    GateInput,
    evaluate_gate,
)
from agent_orchestration.application.orchestration_admission import OrchestrationAdmissionPort
from agent_orchestration.application.orchestration_authority import (
    OrchestrationAction,
    OrchestrationAuthority,
    OrchestrationAuthorizer,
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
    PlanValidationError,
    validate_plan,
)
from agent_orchestration.domain.orchestration import (
    OrchestrationNodeStatus,
    OrchestrationPlanProposal,
    OrchestrationPlanSnapshot,
    OrchestrationRunStatus,
)


class OrchestrationStorePort(Protocol):
    """The store surface the runtime depends on (Postgres adapter exists)."""

    @property
    def deployment_namespace(self) -> str: ...

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

    def __init__(
        self,
        store: OrchestrationStorePort,
        *,
        authorize: OrchestrationAuthorizer | None = None,
        admission: OrchestrationAdmissionPort | None = None,
        require_persisted_gate: bool = False,
        auto_materialize: bool = False,
        gate_reader: Callable[[str], GateInput | None] | None = None,
    ) -> None:
        self._store = store
        self._authorize = authorize
        self._admission = admission
        self._require_persisted_gate = require_persisted_gate
        self._gate_reader = gate_reader
        self._auto_materialize = auto_materialize

    @contextmanager
    def _authorized(self, action: OrchestrationAction) -> Iterator[OrchestrationAuthority]:
        if self._authorize is None:
            raise OrchestrationToolError(
                "orchestration_authority_required", "current server authorization is required"
            )
        with self._authorize(action) as authority:
            if not isinstance(authority, OrchestrationAuthority):
                raise OrchestrationToolError("invalid_authority", "trusted context is required")
            if authority.deployment_namespace != self._store.deployment_namespace:
                raise OrchestrationToolError("orchestration_forbidden", "namespace mismatch")
            yield authority

    def propose_plan(self, proposal: OrchestrationPlanProposal) -> PlanProposalReceipt:
        with self._authorized("propose") as authority:
            run_ref = f"run-{uuid4().hex[:12]}"
            try:
                snapshot = validate_plan(
                    proposal,
                    authority.validation,
                    run_ref=run_ref,
                    parent_task_id=authority.parent_task_id,
                    parent_binding_digest=authority.parent_binding_digest,
                )
            except PlanValidationError as error:
                raise OrchestrationToolError(error.reason_code, error.detail) from None
            self._store.create_run(snapshot)
            if self._auto_materialize:
                self.materialize(run_ref)
            return PlanProposalReceipt(
                run_ref=run_ref,
                plan_revision=snapshot.plan_revision,
                node_keys=tuple(node.proposal.node_key for node in snapshot.nodes),
                reserved_budget=snapshot.reserved_budget,
            )

    def request_task(self, *, run_ref: str, node_key: str) -> TaskRequestReceipt:
        with self._authorized("request") as authority:
            snapshot = self._require_snapshot(run_ref)
            if (
                snapshot.parent_task_id != authority.parent_task_id
                or snapshot.parent_binding_digest != authority.parent_binding_digest
            ):
                raise OrchestrationToolError("orchestration_forbidden", "run binding mismatch")
            if node_key not in {node.proposal.node_key for node in snapshot.nodes}:
                raise OrchestrationToolError("unknown_node", "node does not belong to this run")
        # The admission service owns two committed phases. Never wrap it in the
        # outer authorization work unit; it rechecks authority in both phases.
        if self._admission is not None:
            return self._admission.request_task(run_ref=run_ref, node_key=node_key)
        raise OrchestrationToolError(
            "orchestration_dispatch_unavailable", "durable admission is not configured"
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
        read_status = getattr(self._store, "read_run_status", None)
        if read_status is not None and read_status(run_ref) != "running":
            return LoopDecision(run_ref, (), False, "run_not_running")
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
        *,
        revision: int | None = None,
        child_task_id: str | None = None,
    ) -> LoopDecision:
        """One child terminal report; then re-evaluate (child_wakeup hook)."""

        commit = getattr(self._store, "commit_node_outcome", None)
        if commit is not None:
            decision = commit(
                run_ref, node_key, outcome, revision=revision, child_task_id=child_task_id
            )
            if decision.run_failed or decision.run_blocked:
                return LoopDecision(run_ref, (), False, decision.reason_code)
            return self.evaluate(run_ref)
        snapshot = self._require_snapshot(run_ref)
        if revision is not None and snapshot.plan_revision != revision:
            raise OrchestrationToolError("revision_conflict", "child revision is no longer current")
        state = _state_from_snapshot(snapshot, self._store.read_node_statuses(run_ref))
        decision = on_node_terminal(state, node_key, outcome)
        terminal_status = "failed" if outcome is NodeOutcome.TIMED_OUT else outcome.value
        self._store.transition_node(run_ref, node_key, terminal_status)
        if not decision.retry_keys:
            for key, status in decision.node_updates:
                if key != node_key:
                    self._store.transition_node(run_ref, key, status.value)
        if decision.run_failed or decision.run_blocked or decision.retry_keys:
            self._store.transition_run(
                run_ref,
                OrchestrationRunStatus.RUNNING,
                OrchestrationRunStatus.FAILED
                if decision.run_failed
                else OrchestrationRunStatus.BLOCKED,
            )
            return LoopDecision(
                run_ref,
                (),
                False,
                "retry_requires_replan" if decision.retry_keys else decision.reason_code,
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

        if self._require_persisted_gate:
            gate_input = self._gate_reader(run_ref) if self._gate_reader is not None else None
            if gate_input is None:
                raise OrchestrationToolError(
                    "gate_evidence_unavailable", "current durable gate facts required"
                )
        snapshot = self._require_snapshot(run_ref)
        state = _state_from_snapshot(snapshot, self._store.read_node_statuses(run_ref))
        if not all(node.terminal for node in state.nodes.values()):
            raise OrchestrationToolError(
                "nodes_still_running", f"{run_ref} still has non-terminal nodes"
            )
        if gate_input is not None:
            evaluation = evaluate_gate(f"orchestration:{run_ref}", gate_input)
            if evaluation.blocked:
                raise OrchestrationToolError("gate_blocked", evaluation.reason_code)
            if not evaluation.passed:
                raise OrchestrationToolError("gate_refused", evaluation.reason_code)
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
