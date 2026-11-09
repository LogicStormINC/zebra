"""Atomic scheduler decisions for one exact persisted child/revision."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_orchestration.application.orchestration_runtime import _state_from_snapshot
from agent_orchestration.application.orchestration_scheduling import (
    NodeOutcome,
    SchedulingDecision,
    on_node_terminal,
)
from agent_orchestration.domain.orchestration import NODE_TERMINAL_STATUSES

from agent_storage.postgres.work_unit import postgres_work_unit

if TYPE_CHECKING:
    from agent_storage.postgres.orchestration import PostgresOrchestrationStore


_TERMINAL = {status.value for status in NODE_TERMINAL_STATUSES}


def transition_node(
    store: PostgresOrchestrationStore,
    run_ref: str,
    node_key: str,
    target_status: str,
    *,
    revision: int | None = None,
    source_status: str | None = None,
    child_task_id: str | None = None,
) -> None:
    from agent_storage.postgres.orchestration import OrchestrationStorageError

    with store._database.connect() as connection:
        run = connection.execute(
            "SELECT current_plan_revision FROM orchestration_runs WHERE deployment_namespace=%s "
            "AND run_id=%s FOR UPDATE",
            (store.deployment_namespace, run_ref),
        ).fetchone()
        if run is None or (revision is not None and run["current_plan_revision"] != revision):
            raise OrchestrationStorageError("node revision conflict")
        fixed_revision = run["current_plan_revision"]
        row = connection.execute(
            "SELECT status,child_task_id FROM orchestration_nodes WHERE deployment_namespace=%s "
            "AND run_id=%s AND plan_revision=%s AND node_key=%s FOR UPDATE",
            (store.deployment_namespace, run_ref, fixed_revision, node_key),
        ).fetchone()
        if row is None:
            raise OrchestrationStorageError("node not found")
        if child_task_id is not None and str(row["child_task_id"]) != child_task_id:
            raise OrchestrationStorageError("node child conflict")
        if row["status"] == target_status:
            return
        if row["status"] in _TERMINAL:
            raise OrchestrationStorageError("node terminal conflict")
        allowed_sources = (
            {source_status}
            if source_status is not None
            else {"blocked", "ready", "queued"}
            if target_status == "running"
            else {"running"}
            if target_status in _TERMINAL
            else set()
        )
        if row["status"] not in allowed_sources:
            raise OrchestrationStorageError("node source status conflict")
        connection.execute(
            "UPDATE orchestration_nodes SET status=%s,updated_at=clock_timestamp() "
            "WHERE deployment_namespace=%s AND run_id=%s AND plan_revision=%s AND node_key=%s",
            (target_status, store.deployment_namespace, run_ref, fixed_revision, node_key),
        )


def commit_node_outcome(
    store: PostgresOrchestrationStore,
    run_ref: str,
    node_key: str,
    outcome: NodeOutcome,
    *,
    revision: int | None = None,
    child_task_id: str | None = None,
) -> SchedulingDecision:
    from agent_storage.postgres.orchestration import OrchestrationStorageError

    with postgres_work_unit(store._database):
        with store._database.connect() as connection:
            connection.execute("SET LOCAL lock_timeout='500ms'")
            connection.execute("SET LOCAL statement_timeout='3000ms'")
            run = connection.execute(
                "SELECT current_plan_revision,status FROM orchestration_runs "
                "WHERE deployment_namespace=%s AND run_id=%s FOR UPDATE",
                (store.deployment_namespace, run_ref),
            ).fetchone()
            if run is None or (revision is not None and run["current_plan_revision"] != revision):
                raise OrchestrationStorageError("node revision conflict")
            fixed_revision = int(run["current_plan_revision"])
            snapshot = store.get_snapshot(run_ref, revision=fixed_revision)
            if snapshot is None:
                raise OrchestrationStorageError("missing plan snapshot")
            rows = connection.execute(
                "SELECT node_key,status FROM orchestration_nodes WHERE deployment_namespace=%s "
                "AND run_id=%s AND plan_revision=%s ORDER BY node_key FOR UPDATE",
                (store.deployment_namespace, run_ref, fixed_revision),
            ).fetchall()
            statuses = {row["node_key"]: row["status"] for row in rows}
            target = "failed" if outcome is NodeOutcome.TIMED_OUT else outcome.value
            transition_node(
                store,
                run_ref,
                node_key,
                target,
                revision=fixed_revision,
                source_status="running",
                child_task_id=child_task_id,
            )
            state = _state_from_snapshot(snapshot, statuses)
            # Same terminal replay must not overwrite a later run decision.
            if statuses.get(node_key) == target:
                return SchedulingDecision(reason_code="terminal_already_recorded")
            if run["status"] != "running":
                raise OrchestrationStorageError("run source status conflict")
            decision = on_node_terminal(state, node_key, outcome)
            if decision.retry_keys:
                # ponytail: original identity admits one child only. A retry needs
                # a separately approved new revision; never reopen this node.
                decision = SchedulingDecision(run_blocked=True, reason_code="retry_requires_replan")
            for key, status in decision.node_updates:
                if key != node_key:
                    transition_node(
                        store,
                        run_ref,
                        key,
                        status.value,
                        revision=fixed_revision,
                        source_status=statuses[key],
                    )
            if decision.run_failed or decision.run_blocked:
                connection.execute(
                    "UPDATE orchestration_runs SET status=%s,updated_at=clock_timestamp() "
                    "WHERE deployment_namespace=%s AND run_id=%s",
                    (
                        "failed" if decision.run_failed else "blocked",
                        store.deployment_namespace,
                        run_ref,
                    ),
                )
            return decision
