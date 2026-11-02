"""CA-P7-02B production wiring: child_wakeup → OrchestrationRuntime.complete_node.

The worker loop's terminal-child poll calls the wakeup service; when the
child belongs to an orchestration node (orchestration_nodes.child_task_id)
the same terminal fact must advance the orchestration run. This hook closes
that path without touching the delegation-epoch wakeup itself.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.identifiers import TaskId
from agent_orchestration.application.orchestration_port import (
    OrchestrationToolError,
)
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime
from agent_orchestration.application.orchestration_scheduling import NodeOutcome
from agent_storage.postgres.database import PostgresDatabase


class OrchestrationWakeupHook:
    """Advance orchestration nodes whose child just reached a terminal status."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._runtime = OrchestrationRuntime(_RuntimeStoreAdapter(self._database))

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
                SELECT run_id, node_key FROM orchestration_nodes
                WHERE deployment_namespace = %s AND child_task_id = %s
                """,
                (namespace, str(child_task_id)),
            ).fetchone()
        if binding is None:
            return None
        run_ref, node_key = binding["run_id"], binding["node_key"]
        try:
            decision = self._runtime.complete_node(run_ref, node_key, outcome)
        except OrchestrationToolError:
            return None
        return {
            "run_ref": run_ref,
            "node_key": node_key,
            "reason_code": decision.reason_code or "node_advanced",
        }


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
