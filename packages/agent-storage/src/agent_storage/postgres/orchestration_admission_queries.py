"""Bounded, namespace-scoped checks shared by orchestration admission phases."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, NoReturn, cast

from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_orchestration.application.orchestration_admission import digest, semantic_digest
from agent_orchestration.application.orchestration_authority import OrchestrationAuthority
from agent_orchestration.application.orchestration_port import (
    OrchestrationToolError,
    TaskRequestReceipt,
)
from agent_orchestration.application.orchestration_validation import (
    PlanValidationError,
    validate_plan,
)
from agent_orchestration.domain.orchestration import (
    OrchestrationPlanProposal,
    OrchestrationPlanSnapshot,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation

from agent_storage.postgres.force_stop_signal import stop_requested
from agent_storage.postgres.task_event_positions import _lock_task


def refuse(reason: str, detail: str) -> NoReturn:
    raise OrchestrationToolError(reason, detail)


def parent_in(
    connection: Any, ns: str, authority: OrchestrationAuthority, *, active: bool
) -> TaskBindingSnapshot:
    if authority.deployment_namespace != ns:
        refuse("orchestration_forbidden", "namespace mismatch")
    _lock_task(connection, ns, authority.parent_task_id)
    row = connection.execute(
        """SELECT t.active_segment_id,p.status,b.binding_digest,b.snapshot_json
           FROM agent_tasks t JOIN session_projections p
           ON p.deployment_namespace=t.deployment_namespace AND p.session_id=t.active_segment_id
           JOIN LATERAL (SELECT binding_digest,snapshot_json FROM task_binding_snapshots
             WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id
             ORDER BY binding_revision DESC LIMIT 1) b ON true
           WHERE t.deployment_namespace=%s AND t.task_id=%s FOR UPDATE OF t""",
        (ns, str(authority.parent_task_id)),
    ).fetchone()
    if row is None or row["binding_digest"] != authority.parent_binding_digest:
        refuse("orchestration_forbidden", "current parent binding mismatch")
    if active and (
        row["status"] in {"completed", "failed", "cancelled"}
        or stop_requested(connection, ns, row["active_segment_id"])
    ):
        refuse("orchestration_forbidden", "parent is stopped or terminal")
    return TaskBindingSnapshot.model_validate(row["snapshot_json"])


def snapshot_in(
    connection: Any,
    ns: str,
    authority: OrchestrationAuthority,
    run_ref: str,
    node_key: str,
    *,
    active: bool,
    revision: int | None = None,
) -> tuple[OrchestrationPlanSnapshot, Any]:
    run = connection.execute(
        "SELECT * FROM orchestration_runs WHERE deployment_namespace=%s AND run_id=%s FOR UPDATE",
        (ns, run_ref),
    ).fetchone()
    if run is None:
        refuse("unknown_run", "run does not exist")
    revision = revision or run["current_plan_revision"]
    row = connection.execute(
        "SELECT snapshot_json FROM orchestration_plan_revisions WHERE deployment_namespace=%s "
        "AND run_id=%s AND plan_revision=%s",
        (ns, run_ref, revision),
    ).fetchone()
    if row is None:
        refuse("unknown_run", "run revision is missing")
    snapshot = OrchestrationPlanSnapshot.model_validate(row["snapshot_json"])
    if (
        snapshot.parent_task_id != authority.parent_task_id
        or snapshot.parent_binding_digest != authority.parent_binding_digest
    ):
        refuse("orchestration_forbidden", "run parent binding mismatch")
    if active and (run["status"] != "running" or revision != run["current_plan_revision"]):
        refuse("node_not_ready", "run is not the current running revision")
    node = next((n.proposal for n in snapshot.nodes if n.node_key == node_key), None)
    if node is None:
        refuse("unknown_node", "node does not belong to run")
    return snapshot, node


def eligible(
    connection: Any,
    ns: str,
    snapshot: OrchestrationPlanSnapshot,
    node: Any,
    authority: OrchestrationAuthority,
    *,
    owned: BudgetReservation | None = None,
) -> None:
    # Reuse the pure validator for this node's CURRENT role/capability/resource/budget ceiling.
    try:
        validate_plan(
            OrchestrationPlanProposal(
                objective=snapshot.run_ref,
                nodes=(node,),
                dependencies=(),
                max_parallelism=1,
                synthesis_instruction="admit frozen node",
            ),
            replace(authority.validation, parent_remaining_budget=owned)
            if owned is not None
            else authority.validation,
            run_ref=snapshot.run_ref,
            parent_task_id=snapshot.parent_task_id,
            parent_binding_digest=snapshot.parent_binding_digest,
        )
    except PlanValidationError as error:
        raise OrchestrationToolError(error.reason_code, error.detail) from None

    states = connection.execute(
        "SELECT node_key,status,child_task_id FROM orchestration_nodes "
        "WHERE deployment_namespace=%s "
        "AND run_id=%s AND plan_revision=%s FOR UPDATE",
        (ns, snapshot.run_ref, snapshot.plan_revision),
    ).fetchall()
    by_key = {r["node_key"]: r for r in states}
    current = by_key.get(node.node_key)
    if current is None or current["status"] not in {"ready", "blocked"} or current["child_task_id"]:
        refuse("node_not_ready", "node is already dispatched or not runnable")
    parents = [e.from_node for e in snapshot.dependencies if e.to_node == node.node_key]
    if any(by_key[key]["status"] != "completed" for key in parents):
        refuse("node_not_ready", "node dependencies are not completed")
    # ponytail: snapshots do not freeze a parallelism cap yet; retain the existing
    # serial scheduling limit until the snapshot contract explicitly carries it.
    if any(
        r["status"] in {"queued", "running", "waiting_approval", "waiting_children", "verifying"}
        for r in states
    ):
        refuse("node_not_ready", "the run already has an active child")


def original_in(connection: Any, ns: str, key: str) -> dict[str, Any] | None:
    return cast(
        dict[str, Any] | None,
        connection.execute(
            "SELECT * FROM orchestration_admission_originals WHERE deployment_namespace=%s "
            "AND original_key=%s",
            (ns, key),
        ).fetchone(),
    )


def check_original(row: Any, ns: str, snapshot: OrchestrationPlanSnapshot, node_key: str) -> None:
    if row["semantic_digest"] != semantic_digest(ns, snapshot, node_key) or row[
        "payload_digest"
    ] != digest(row["payload"]):
        refuse("orchestration_original_conflict", "original input no longer matches frozen request")


def receipt(row: Any) -> TaskRequestReceipt:
    if row["state"] != "admitted" or row["receipt"] is None:
        refuse("orchestration_admission_unknown", row["original_key"])
    return TaskRequestReceipt(**row["receipt"])


def budget_in(
    connection: Any,
    ns: str,
    authority: OrchestrationAuthority,
    reservation: BudgetReservation,
    *,
    existing: bool = False,
) -> None:
    from psycopg.types.json import Jsonb

    current = authority.validation.parent_remaining_budget
    connection.execute(
        "INSERT INTO orchestration_parent_budgets VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (
            ns,
            str(authority.parent_task_id),
            authority.parent_binding_digest,
            Jsonb(current.model_dump(mode="json")),
        ),
    )
    row = connection.execute(
        "SELECT * FROM orchestration_parent_budgets WHERE deployment_namespace=%s "
        "AND parent_task_id=%s FOR UPDATE",
        (ns, str(authority.parent_task_id)),
    ).fetchone()
    if row["binding_digest"] != authority.parent_binding_digest:
        refuse("orchestration_forbidden", "parent budget binding changed")
    # ponytail: indexed O(N originals for this parent) aggregate, bounded by the
    # transaction deadline; sustained large parents need transactional counters.
    used = connection.execute(
        """SELECT COALESCE(sum(COALESCE((usage->>'model_tokens')::numeric,
                  (reservation->>'model_tokens')::numeric)),0) AS model_tokens,
               COALESCE(sum(COALESCE((usage->>'tool_calls')::numeric,
                  (reservation->>'tool_calls')::numeric)),0) AS tool_calls,
               COALESCE(sum(COALESCE((usage->>'runtime_seconds')::numeric,
                  (reservation->>'runtime_seconds')::numeric)),0) AS runtime_seconds
           FROM orchestration_admission_originals
           WHERE deployment_namespace=%s AND parent_task_id=%s""",
        (ns, str(authority.parent_task_id)),
    ).fetchone()
    ceiling = BudgetReservation.model_validate(row["ceiling"])
    approved = authority.approved_budget
    if approved is None:
        refuse("orchestration_budget_authority_required", "current approved budget is required")
    effective = BudgetReservation(
        **{
            name: min(getattr(ceiling, name), getattr(approved, name))
            for name in ("model_tokens", "tool_calls", "runtime_seconds")
        }
    )
    charged = BudgetReservation(
        **{
            name: int(used[name]) + (0 if existing else getattr(reservation, name))
            for name in ("model_tokens", "tool_calls", "runtime_seconds")
        }
    )
    if not effective.covers(charged) or (not existing and not current.covers(reservation)):
        refuse("budget_beyond_parent", "durable parent budget is exhausted")


def terminal_child_in(connection: Any, ns: str, row: Any) -> dict[str, Any] | None:
    """Lock and verify the real child's original lineage, active segment and full binding."""
    from uuid import UUID

    from agent_core.domain.identifiers import TaskId

    _lock_task(connection, ns, TaskId(UUID(str(row["child_task_id"]))))
    child = connection.execute(
        """SELECT t.active_segment_id,p.status,b.snapshot_json,l.parent_task_id,
                  l.parent_binding_digest,l.child_binding_digest,l.plan_revision,l.node_key,
                  n.child_task_id AS node_child
           FROM agent_tasks t JOIN session_projections p
             ON p.deployment_namespace=t.deployment_namespace AND p.session_id=t.active_segment_id
           JOIN LATERAL (SELECT snapshot_json FROM task_binding_snapshots
             WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id
             ORDER BY binding_revision DESC LIMIT 1) b ON true
           JOIN subagent_delegation_links l ON l.deployment_namespace=t.deployment_namespace
             AND l.child_task_id=t.task_id
           JOIN orchestration_nodes n ON n.deployment_namespace=t.deployment_namespace
             AND n.run_id=%s AND n.plan_revision=%s AND n.node_key=%s
           WHERE t.deployment_namespace=%s AND t.task_id=%s FOR UPDATE OF t,p""",
        (row["run_id"], row["plan_revision"], row["node_key"], ns, row["child_task_id"]),
    ).fetchone()
    expected = TaskBindingSnapshot.model_validate(row["payload"]["binding"])
    if (
        child is None
        or child["snapshot_json"] != row["payload"]["binding"]
        or str(child["parent_task_id"]) != str(row["parent_task_id"])
        or child["parent_binding_digest"]
        != row["payload"]["delegation"]["expected_parent_binding_digest"]
        or child["child_binding_digest"] != expected.binding_digest
        or child["plan_revision"] != row["plan_revision"]
        or child["node_key"] != row["node_key"]
        or str(child["node_child"]) != str(row["child_task_id"])
    ):
        refuse("orchestration_usage_conflict", "child no longer matches original binding/lineage")
    return child if child["status"] in {"completed", "failed", "cancelled"} else None
