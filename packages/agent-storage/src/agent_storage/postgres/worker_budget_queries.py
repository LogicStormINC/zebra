"""Bounded native lease/Task/STOP checks shared by ordinary Worker accounting."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.worker_budget import WorkerBudgetBinding, WorkerBudgetError

from agent_storage.postgres.coverage_authority import lock_coverage_lease, validate_coverage_lease
from agent_storage.postgres.force_stop_signal import stop_requested
from agent_storage.postgres.leases import lock_session_lease_boundary
from agent_storage.postgres.task_event_positions import _lock_task


def boundary(connection: Any, ns: str, binding: WorkerBudgetBinding) -> Any:
    lock_session_lease_boundary(connection, ns, binding.session_id)
    lease = lock_coverage_lease(connection, ns, binding.session_id)
    _lock_task(connection, ns, TaskId(UUID(binding.task_id)))
    row = connection.execute(
        """SELECT t.active_segment_id,p.status,p.namespace_id,b.binding_digest,b.snapshot_json
        FROM agent_tasks t JOIN session_projections p
          ON p.deployment_namespace=t.deployment_namespace AND p.session_id=t.active_segment_id
        JOIN LATERAL (SELECT binding_digest,snapshot_json FROM task_binding_snapshots
          WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id
          ORDER BY binding_revision DESC LIMIT 1) b ON true
        WHERE t.deployment_namespace=%s AND t.task_id=%s FOR UPDATE OF t""",
        (ns, binding.task_id),
    ).fetchone()
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    validate_coverage_lease(lease, binding.fence, now)
    if (
        row is None
        or row["active_segment_id"] != binding.session_id
        or row["binding_digest"] != binding.binding_digest
        or row["status"] in {"completed", "failed", "cancelled"}
        or stop_requested(connection, ns, binding.session_id)
    ):
        raise WorkerBudgetError("Worker Task/binding/segment/STOP boundary changed")
    unreserved_child = connection.execute(
        """SELECT 1 FROM subagent_delegation_links l
           WHERE l.deployment_namespace=%s AND l.child_task_id=%s AND NOT EXISTS (
             SELECT 1 FROM orchestration_admission_originals o
             WHERE o.deployment_namespace=l.deployment_namespace
               AND o.child_task_id=l.child_task_id AND o.state='admitted') LIMIT 1""",
        (ns, binding.task_id),
    ).fetchone()
    if unreserved_child is not None:
        raise WorkerBudgetError("delegated child lacks a durable parent budget reservation")
    settled = connection.execute(
        "SELECT 1 FROM orchestration_admission_originals WHERE deployment_namespace=%s "
        "AND child_task_id=%s AND usage IS NOT NULL LIMIT 1",
        (ns, binding.task_id),
    ).fetchone()
    if settled is not None:
        raise WorkerBudgetError(
            "settled child Task cannot resume spending its released reservation"
        )
    frozen = TaskBindingSnapshot.model_validate(row["snapshot_json"])
    host = frozen.host_capability
    if (
        frozen.task_id != binding.task_id
        or frozen.binding_digest != binding.binding_digest
        or host.bound_at > now
        or frozen.bound_at > now
        or (host.grant_expires_at is not None and host.grant_expires_at <= now)
    ):
        raise WorkerBudgetError("Worker frozen authority expired or changed")
    if row["namespace_id"] is not None and row["namespace_id"] != host.namespace_id:
        raise WorkerBudgetError("Worker Host namespace changed")
    if host.host_context is not None:
        if host.grant_digest != host_context_digest(host.host_context):
            raise WorkerBudgetError("Worker frozen Host grant digest changed")
        if host.host_context.expires_at is not None and host.host_context.expires_at <= now:
            raise WorkerBudgetError("Worker Host context expired")
        limits = host.host_context.limits
        if (
            binding.max_model_tokens > limits.max_model_tokens
            or binding.max_runtime_seconds > limits.max_runtime_seconds
        ):
            raise WorkerBudgetError("Worker limits exceed frozen Host ceiling")
    return now


def remaining(
    connection: Any, ns: str, binding: WorkerBudgetBinding, *, require_segment: bool = True
) -> float:
    now = boundary(connection, ns, binding)
    row = connection.execute(
        "SELECT * FROM worker_task_budgets WHERE deployment_namespace=%s AND task_id=%s FOR UPDATE",
        (ns, binding.task_id),
    ).fetchone()
    if row is None or row["binding_digest"] != binding.binding_digest:
        raise WorkerBudgetError("Task budget is missing or bound to another authority")
    if require_segment and (
        row["last_session_id"] != binding.session_id
        or row["last_fence"] != binding.fence.model_dump(mode="json")
        or row["last_attempt"] != binding.attempt_number
    ):
        raise WorkerBudgetError("Task budget active execution journal moved")
    inherited = ancestor_deadline(connection, ns, binding.task_id)
    deadline = min(row["deadline"], inherited) if inherited is not None else row["deadline"]
    seconds = (deadline - now).total_seconds()
    if seconds <= 0:
        raise WorkerBudgetError("Task execution absolute deadline exceeded")
    return float(seconds)


def child_charges(connection: Any, ns: str, task_id: Any) -> tuple[int, int, int]:
    row = connection.execute(
        """SELECT coalesce(sum((coalesce(usage,reservation)->>'model_tokens')::bigint),0) AS tokens,
          coalesce(sum((coalesce(usage,reservation)->>'tool_calls')::bigint),0) AS tools,
          coalesce(sum((coalesce(usage,reservation)->>'runtime_seconds')::bigint),0) AS seconds
          FROM orchestration_admission_originals
          WHERE deployment_namespace=%s AND parent_task_id=%s""",
        (ns, task_id),
    ).fetchone()
    return int(row["tokens"]), int(row["tools"]), int(row["seconds"])


ANCESTOR_DEADLINE_SQL = """WITH RECURSIVE ancestors(task_id,depth) AS (
          SELECT %s::uuid,0 UNION ALL
          SELECT l.parent_task_id,a.depth+1 FROM ancestors a JOIN subagent_delegation_links l
            ON l.deployment_namespace=%s AND l.child_task_id=a.task_id WHERE a.depth<32)
          SELECT min(b.deadline) AS deadline,max(a.depth) AS depth,
            count(*) FILTER (WHERE a.depth>0 AND b.task_id IS NULL) AS missing
          FROM ancestors a LEFT JOIN worker_task_budgets b
            ON b.deployment_namespace=%s AND b.task_id=a.task_id"""


def validated_ancestor_deadline(row: Any) -> Any:
    if row["depth"] >= 32 or row["missing"]:
        raise WorkerBudgetError("ancestor Task budget is missing or exceeds bounded lineage")
    return row["deadline"]


def ancestor_deadline(connection: Any, ns: str, task_id: Any) -> Any:
    row = connection.execute(ANCESTOR_DEADLINE_SQL, (task_id, ns, ns)).fetchone()
    return validated_ancestor_deadline(row)


def tools_confirmed(connection: Any, ns: str, task_id: Any) -> bool:
    unresolved = connection.execute(
        """SELECT 1 FROM effect_outbox o JOIN execution_segments s
             ON s.deployment_namespace=o.deployment_namespace
               AND s.session_id=o.execution_session_id
           WHERE o.deployment_namespace=%s AND s.task_id=%s
             AND o.status NOT IN ('succeeded','failed_no_effect')
           UNION ALL SELECT 1 FROM client_effects WHERE deployment_namespace=%s AND task_id=%s
             AND status NOT IN ('succeeded','failed','declined','unavailable','stale_ui_state')
           LIMIT 1""",
        (ns, task_id, ns, task_id),
    ).fetchone()
    if unresolved is not None:
        return False
    rows = connection.execute(
        """SELECT r.call_id,e.event_type,e.payload FROM worker_tool_reservations r
           LEFT JOIN LATERAL (SELECT event_type,payload FROM session_events e
             JOIN execution_segments s ON s.deployment_namespace=e.deployment_namespace
               AND s.session_id=e.session_id
             WHERE e.deployment_namespace=r.deployment_namespace AND s.task_id=r.task_id
               AND e.payload->>'tool_call_id'=r.call_id::text
               AND e.event_type IN ('tool_execution_completed','tool_execution_failed')
             ORDER BY e.task_sequence DESC,e.sequence DESC LIMIT 1) e ON true
           WHERE r.deployment_namespace=%s AND r.task_id=%s""",
        (ns, task_id),
    ).fetchall()
    seen: set[Any] = set()
    for row in rows:
        if row["call_id"] in seen or row["payload"] is None:
            return False
        seen.add(row["call_id"])
        payload = row["payload"]
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            return False
        if (
            metadata.get("execution_state") == "unknown"
            or metadata.get("business_outcome") == "unknown"
            or metadata.get("effect_status") in {"reserved", "executing", "uncertain"}
            or metadata.get("client_effect_deferred") is True
            or metadata.get("client_effect_status") in {"pending", "delivered", "uncertain"}
        ):
            return False
        receipt = metadata.get("host_effect_receipt")
        if receipt is not None:
            from agent_core.domain.host_effect_receipts import HostEffectReceipt

            try:
                if not HostEffectReceipt.model_validate(receipt).reconciled:
                    return False
            except ValueError:
                return False
        if row["event_type"] == "tool_execution_completed":
            if payload.get("status") != "executed":
                return False
        elif payload.get("status") != "failed" or metadata.get("execution_state") not in {
            "not_executed",
            "executed",
        }:
            return False
    return True


def model_calls(connection: Any, ns: str, task_id: Any) -> Iterator[Any]:
    cursor = UUID(int=0)
    while True:
        page = connection.execute(
            """SELECT r.*,s.task_id AS segment_task FROM worker_model_reservations r
               LEFT JOIN execution_segments s ON s.deployment_namespace=r.deployment_namespace
                 AND s.session_id=r.session_id
               WHERE r.deployment_namespace=%s AND r.task_id=%s AND r.reservation_id>%s
               ORDER BY r.reservation_id LIMIT 100""",
            (ns, task_id, cursor),
        ).fetchall()
        if not page:
            return
        yield from page
        cursor = page[-1]["reservation_id"]
