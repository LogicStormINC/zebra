"""CA-P7-02B production wiring: child_wakeup → OrchestrationRuntime.complete_node.

The worker loop's terminal-child poll calls the wakeup service; when the
child belongs to an orchestration node (orchestration_nodes.child_task_id)
the same terminal fact must advance the orchestration run. This hook closes
that path without touching the delegation-epoch wakeup itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent_core.domain.identifiers import TaskId
from agent_orchestration.application.orchestration_port import (
    OrchestrationToolError,
)
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime
from agent_orchestration.application.orchestration_scheduling import NodeOutcome
from agent_storage.postgres.database import PostgresDatabase

if TYPE_CHECKING:
    from zebra_agent_worker.execution_tool_gateway import ModelRequestBudgetFactory
    from zebra_agent_worker.orchestration_composition import PostgresOrchestrationFactory


class OrchestrationWakeupHook:
    """Advance orchestration nodes whose child just reached a terminal status."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        settle_original: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._settle_original = settle_original
        self._reconcile_after = ""
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._runtime = OrchestrationRuntime(
            _RuntimeStoreAdapter(self._database), require_persisted_gate=True
        )

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def on_child_terminal(
        self, child_task_id: TaskId, outcome: NodeOutcome
    ) -> dict[str, str] | None:
        """Find the (run, node) bound to this child and complete the node.

        Returns public coordinates when a node advanced, None when the child
        is not part of any orchestration run. Unknown runs (store misses) are
        swallowed typed — a legacy child must never break the wakeup loop.
        """

        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            binding = connection.execute(
                """
                SELECT run_id, plan_revision, node_key FROM orchestration_nodes
                WHERE deployment_namespace = %s AND child_task_id = %s
                """,
                (namespace, str(child_task_id)),
            ).fetchone()
        if binding is None:
            return None
        run_ref, node_key = binding["run_id"], binding["node_key"]
        try:
            decision = self._runtime.complete_node(
                run_ref,
                node_key,
                outcome,
                revision=int(binding["plan_revision"]),
                child_task_id=str(child_task_id),
            )
        except OrchestrationToolError:
            return None
        if decision.run_complete:
            try:
                self._runtime.synthesize(run_ref)
            except OrchestrationToolError as error:
                return {"run_ref": run_ref, "node_key": node_key, "reason_code": error.reason_code}
        return {
            "run_ref": run_ref,
            "node_key": node_key,
            "reason_code": decision.reason_code or "node_advanced",
        }

    def reconcile_pending(self, *, limit: int = 16) -> None:
        """Retry completion/usage independently of delegation wakeup consumption."""
        if not 1 <= limit <= 64:
            raise ValueError("orchestration reconciliation limit must be 1..64")
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT o.original_key,o.parent_task_id,o.child_task_id,p.status "
                "FROM orchestration_admission_originals o JOIN agent_tasks t "
                "ON t.deployment_namespace=o.deployment_namespace AND t.task_id=o.child_task_id "
                "JOIN session_projections p ON p.deployment_namespace=t.deployment_namespace "
                "AND p.session_id=t.active_segment_id "
                "WHERE o.deployment_namespace=%s AND o.state='admitted' AND o.usage IS NULL "
                "AND p.status IN ('completed','failed','cancelled') AND o.original_key>%s "
                "ORDER BY o.original_key LIMIT %s",
                (self.deployment_namespace, self._reconcile_after, limit),
            ).fetchall()
        self._reconcile_after = rows[-1]["original_key"] if rows else ""
        for row in rows:
            # A stale revision may still settle its exact original usage; it must
            # never advance the replacement revision. Failure in either operation
            # leaves the original discoverable by the next independent scan.
            try:
                outcome = outcome_for_child_status(row["status"])
                if outcome is not None:
                    self.on_child_terminal(row["child_task_id"], outcome)
            except Exception:
                pass
            if self._settle_original is not None:
                try:
                    self._settle_original(row["original_key"], str(row["parent_task_id"]))
                except Exception:
                    pass  # retry remains discoverable independently of wakeup state


_OUTCOME_FOR_STATUS = {
    "completed": NodeOutcome.COMPLETED,
    "failed": NodeOutcome.FAILED,
    "cancelled": NodeOutcome.CANCELLED,
    "timed_out": NodeOutcome.TIMED_OUT,
}


def outcome_for_child_status(status: str) -> NodeOutcome | None:
    """Map the wakeup poll's child status strings onto node outcomes."""

    return _OUTCOME_FOR_STATUS.get(status)


class _RuntimeStoreAdapter:
    """Reuse PostgresOrchestrationStore methods over one shared database."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._store = _BoundStore(database)

    def __getattr__(self, name: str) -> Any:  # delegate to the bound store
        return getattr(self._store, name)


class _BoundStore:
    """PostgresOrchestrationStore over an externally owned database."""

    def __init__(self, database: PostgresDatabase) -> None:
        from agent_storage.postgres.orchestration import PostgresOrchestrationStore

        self._inner = PostgresOrchestrationStore.__new__(PostgresOrchestrationStore)
        self._inner._database = database

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def compose_orchestration(
    dsn: str | None,
    namespace: str | None,
    *,
    model_request_budget_factory: ModelRequestBudgetFactory | None = None,
) -> tuple[PostgresOrchestrationFactory | None, OrchestrationWakeupHook | None]:
    """Bind normal-entry and independent reconciliation to the same database."""
    from zebra_agent_worker.orchestration_composition import PostgresOrchestrationFactory

    if not dsn or not namespace:
        return None, None
    factory = PostgresOrchestrationFactory(
        dsn, namespace, model_request_budget_factory=model_request_budget_factory
    )
    hook = OrchestrationWakeupHook(
        dsn, deployment_namespace=namespace, settle_original=factory.settle_original
    )
    return factory, hook
