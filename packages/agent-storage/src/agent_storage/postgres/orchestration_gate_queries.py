"""Bounded real execution observations; model summaries and v27 receipts are excluded."""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from agent_core.domain.bundle_definition import BundleDefinitionSnapshot, parse_definition_snapshot
from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision,
    ExecutionAuthorityRevalidation,
    ExecutionAuthoritySnapshot,
)
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.worker_budget import (
    ModelBudgetReservation,
    WorkerBudgetBinding,
    trusted_usage,
)
from agent_orchestration.application.orchestration_admission import digest
from agent_orchestration.application.orchestration_completion_gate import definition_binding_matches

from agent_storage.postgres import orchestration_admission_queries as admission
from agent_storage.postgres.force_stop_signal import stop_requested
from agent_storage.postgres.worker_budget_queries import boundary, model_calls, tools_confirmed

# ponytail: 256 canonical events/artifacts per child; larger runs need bounded pagination.
MAX_FACTS_PER_CHILD = 256


def parent_boundary(c: Any, ns: str, snapshot: Any) -> dict[str, Any]:
    row = c.execute(
        "SELECT *,ceil(extract(epoch FROM (deadline-started_at)))::bigint AS runtime "
        "FROM worker_task_budgets WHERE deployment_namespace=%s AND task_id=%s",
        (ns, str(snapshot.parent_task_id)),
    ).fetchone()
    if row is None or row["binding_digest"] != snapshot.parent_binding_digest:
        admission.refuse("gate_authority_unavailable", "current parent Worker journal required")
    binding = WorkerBudgetBinding(
        str(snapshot.parent_task_id),
        SessionId(UUID(str(row["last_session_id"]))),
        snapshot.parent_binding_digest,
        LeaseFence.model_validate(row["last_fence"]),
        int(row["last_attempt"]),
        int(row["max_model_tokens"]),
        int(row["runtime"]),
        int(row["max_tool_calls"]),
    )
    # Rechecks database epoch, exact owner/fence/expiry, active segment, current
    # binding, STOP ancestry and frozen Host limits; last_fence alone grants nothing.
    now = boundary(c, ns, binding)
    if row["deadline"] <= now:
        admission.refuse("gate_authority_unavailable", "parent execution deadline expired")
    total = 0
    for call in model_calls(c, ns, binding.task_id):
        receipt = call["receipt"]
        if not isinstance(receipt, dict) or not receipt.get("id"):
            admission.refuse("gate_usage_unavailable", "parent model outcome is unknown")
        try:
            total += trusted_usage(
                {
                    "prompt_tokens": receipt.get("prompt"),
                    "completion_tokens": receipt.get("output"),
                    "total_tokens": receipt.get("total"),
                },
                ModelBudgetReservation(
                    str(call["reservation_id"]),
                    call["request_digest"],
                    call["input_upper"],
                    call["output_cap"],
                ),
            )[2]
        except ValueError:
            admission.refuse("gate_usage_unavailable", "parent model receipt is invalid")
    if total != row["charged_tokens"] or not tools_confirmed(c, ns, binding.task_id):
        admission.refuse("gate_usage_unavailable", "parent usage/effects are not confirmed")
    return {
        "session_id": str(binding.session_id),
        "binding_digest": binding.binding_digest,
        "fence": binding.fence.model_dump(mode="json"),
        "attempt": binding.attempt_number,
    }


def child_facts(c: Any, ns: str, snapshot: Any, node: Any, state: Any) -> dict[str, Any]:
    row = c.execute(
        "SELECT * FROM orchestration_admission_originals WHERE deployment_namespace=%s "
        "AND run_id=%s AND plan_revision=%s AND node_key=%s",
        (ns, snapshot.run_ref, snapshot.plan_revision, node.node_key),
    ).fetchone()
    if row is None or row["state"] != "admitted" or row["receipt"] is None:
        admission.refuse("gate_original_unavailable", "exact admitted original is required")
    admission.check_original(row, ns, snapshot, node.node_key)
    child = admission.terminal_child_in(c, ns, row)
    if child is None or str(row["child_task_id"]) != str(state["child_task_id"]):
        admission.refuse("gate_child_conflict", "exact current terminal child is required")
    if child["status"] != state["status"]:
        admission.refuse("gate_child_conflict", "node and current child outcome differ")
    sid = child["active_segment_id"]
    terminal = c.execute(
        "SELECT event_id,event_type FROM session_events WHERE deployment_namespace=%s "
        "AND task_id=%s AND session_id=%s "
        "AND event_type IN ('session_completed','session_failed','session_cancelled') "
        "ORDER BY sequence DESC LIMIT 1",
        (ns, row["child_task_id"], sid),
    ).fetchone()
    if terminal is None or terminal["event_type"] != "session_" + child["status"]:
        admission.refuse("gate_child_conflict", "current canonical terminal Event is required")
    validate_child_authority(c, ns, sid, child["snapshot_json"])
    segments = c.execute(
        "SELECT count(*) AS n FROM execution_segments WHERE deployment_namespace=%s AND task_id=%s",
        (ns, row["child_task_id"]),
    ).fetchone()["n"]
    attempts = c.execute(
        "SELECT count(*) AS n FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
        "AND event_type='harness_attempt_started'",
        (ns, row["child_task_id"]),
    ).fetchone()["n"]
    if segments != 1 or attempts != 1:
        admission.refuse("readonly_evidence_conflict", "one execution segment and Attempt required")
    tools = c.execute(
        """SELECT event_id,sequence,event_type,payload,actor FROM session_events
          WHERE deployment_namespace=%s AND task_id=%s AND session_id=%s
            AND event_type IN ('tool_call_proposed','tool_execution_started',
                              'tool_execution_completed','tool_execution_failed')
          ORDER BY sequence LIMIT %s""",
        (ns, row["child_task_id"], sid, MAX_FACTS_PER_CHILD + 1),
    ).fetchall()
    reservations = c.execute(
        "SELECT call_id FROM worker_tool_reservations WHERE deployment_namespace=%s "
        "AND task_id=%s LIMIT %s",
        (ns, row["child_task_id"], MAX_FACTS_PER_CHILD + 1),
    ).fetchall()
    readonly, successful = readonly_tools(tools, {str(r["call_id"]) for r in reservations})
    effects = c.execute(
        "SELECT 1 FROM effect_outbox o JOIN execution_segments s ON "
        "s.deployment_namespace=o.deployment_namespace AND s.session_id=o.execution_session_id "
        "WHERE o.deployment_namespace=%s AND s.task_id=%s UNION ALL "
        "SELECT 1 FROM client_effects WHERE deployment_namespace=%s AND task_id=%s LIMIT 1",
        (ns, row["child_task_id"], ns, row["child_task_id"]),
    ).fetchone()
    artifacts = c.execute(
        """SELECT a.artifact_id,a.sha256,a.event_id,a.lifecycle_revision
          FROM artifact_payload_metadata a
          JOIN session_events e ON e.deployment_namespace=a.deployment_namespace
            AND e.session_id=a.session_id AND e.event_id=a.event_id AND e.sequence=a.event_sequence
          WHERE a.deployment_namespace=%s AND a.session_id=%s
            AND a.lifecycle_status='finalized' AND a.object_verified_at IS NOT NULL
            AND e.event_type='tool_execution_completed'
            AND e.payload#>>'{metadata,artifact_uri}'=a.artifact_uri
            AND (a.retained_until IS NULL OR a.retained_until>clock_timestamp())
          ORDER BY a.artifact_id LIMIT %s FOR SHARE OF a""",
        (ns, sid, MAX_FACTS_PER_CHILD + 1),
    ).fetchall()
    if (
        len(tools) > MAX_FACTS_PER_CHILD
        or len(artifacts) > MAX_FACTS_PER_CHILD
        or len(reservations) > MAX_FACTS_PER_CHILD
    ):
        admission.refuse("gate_evidence_limit", "bounded observation capacity exceeded")
    return {
        "node_key": node.node_key,
        "original_key": row["original_key"],
        "payload_digest": row["payload_digest"],
        "child_task_id": str(row["child_task_id"]),
        "binding_digest": child["child_binding_digest"],
        "session_id": str(sid),
        "status": child["status"],
        "terminal_event_id": str(terminal["event_id"]),
        "readonly": readonly and effects is None,
        "tools": [
            {
                "event_id": str(e["event_id"]),
                "sequence": e["sequence"],
                "payload_digest": digest(e["payload"]),
                "successful": str(e["event_id"]) in successful,
            }
            for e in tools
        ],
        "artifacts": [
            {k: str(v) for k, v in a.items()} for a in artifacts if str(a["event_id"]) in successful
        ],
        "effects_confirmed": tools_confirmed(c, ns, row["child_task_id"]),
    }


def validate_child_authority(c: Any, ns: str, sid: Any, payload: Any) -> None:
    binding = TaskBindingSnapshot.model_validate(payload)
    host = binding.host_capability
    context = host.host_context
    now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    if (
        context is None
        or host.grant_expires_at is None
        or host.grant_expires_at <= now
        or context.expires_at is None
        or context.expires_at <= now
        or binding.bound_at > now
        or host.bound_at > now
        or host_context_digest(context) != host.grant_digest
        or stop_requested(c, ns, sid)
    ):
        admission.refuse(
            "gate_child_authority_unavailable", "current child grant/STOP refuses completion"
        )
    prepared = c.execute(
        "SELECT payload FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
        "AND event_type='task_prepared' ORDER BY task_sequence LIMIT 1",
        (ns, binding.task_id),
    ).fetchone()
    definition = (
        None
        if prepared is None
        else parse_definition_snapshot(prepared["payload"].get("definition_snapshot"))
    )
    if not isinstance(definition, BundleDefinitionSnapshot):
        admission.refuse(
            "gate_child_authority_unavailable", "frozen native child Definition required"
        )
    current_execution_authority(c, ns, binding, definition, 1, now)


def readonly_tools(events: list[Any], reservations: set[str]) -> tuple[bool, set[str]]:
    """Pair actual proposal/start/terminal facts; output text is never a verifier."""
    calls: dict[str, list[Any]] = {}
    for event in events:
        payload = event["payload"]
        key = payload.get("tool_call_id")
        if not isinstance(key, str) or payload.get("tool_name") != "files.read":
            return False, set()
        calls.setdefault(key, []).append(event)
    if set(calls) != reservations:
        return False, set()
    successful: set[str] = set()
    for facts in calls.values():
        if (
            len(facts) != 3
            or [f["event_type"] for f in facts[:2]]
            != [
                "tool_call_proposed",
                "tool_execution_started",
            ]
            or facts[2]["event_type"] not in {"tool_execution_completed", "tool_execution_failed"}
        ):
            return False, set()
        if [f["actor"] for f in facts] != ["harness", "harness", "tool"]:
            return False, set()
        proposed, started, terminal = (f["payload"] for f in facts)
        if (facts[2]["event_type"], terminal.get("status")) not in {
            ("tool_execution_completed", "executed"),
            ("tool_execution_failed", "failed"),
        }:
            return False, set()
        if any(p.get("attempt_number") != 1 for p in (proposed, started, terminal)):
            return False, set()
        arguments = proposed.get("arguments")
        if not isinstance(arguments, dict) or set(arguments) != {"path"}:
            return False, set()
        path = arguments["path"]
        if not isinstance(path, str) or not path.strip():
            return False, set()
        if terminal.get("status") == "executed":
            if terminal.get("metadata", {}).get("path") != str(Path(path.strip())):
                return False, set()
            successful.add(str(facts[2]["event_id"]))
    return True, successful


def current_execution_authority(
    c: Any,
    ns: str,
    binding: TaskBindingSnapshot,
    snapshot: Any,
    attempt_number: int | None,
    now: datetime,
) -> ExecutionAuthoritySnapshot:
    row = c.execute(
        "SELECT e.event_type,e.payload FROM session_events e JOIN agent_tasks t "
        "ON t.deployment_namespace=e.deployment_namespace AND t.task_id=e.task_id "
        "AND t.active_segment_id=e.session_id WHERE e.deployment_namespace=%s "
        "AND e.task_id=%s AND e.event_type IN ('execution_authority_resolved',"
        "'execution_authority_revalidated') ORDER BY e.task_sequence DESC LIMIT 1",
        (ns, binding.task_id),
    ).fetchone()
    if row is None:
        admission.refuse(
            "orchestration_forbidden", "current durable execution authority is unavailable"
        )
    if row["event_type"] == "execution_authority_resolved":
        proof = ExecutionAuthoritySnapshot.model_validate(row["payload"])
    else:
        revalidated = ExecutionAuthorityRevalidation.model_validate(row["payload"])
        if (
            revalidated.decision
            not in {
                ExecutionAuthorityDecision.ALLOWED,
                ExecutionAuthorityDecision.NARROWED,
            }
            or revalidated.effective_snapshot is None
        ):
            admission.refuse(
                "orchestration_forbidden", "current execution authority denies orchestration"
            )
        proof = revalidated.effective_snapshot
    host = binding.host_capability
    if (
        proof.resolution
        not in {ExecutionAuthorityDecision.ALLOWED, ExecutionAuthorityDecision.NARROWED}
        or proof.expires_at <= now
        or proof.validated_at > now
        or (attempt_number is not None and proof.attempt_number != attempt_number)
        or proof.agent_definition_snapshot_digest
        != binding.agent_capability_ceiling.definition_snapshot_digest
        or not definition_binding_matches(proof.agent_definition_snapshot_digest, snapshot)
        or proof.authority_issuer != host.authority_issuer
        or proof.source_authority_digest != binding.binding_digest
        or proof.policy_effective_digest != binding.zebra_policy_digest
        or proof.namespace_id != host.namespace_id
        or "agent.execute" not in proof.granted_authorities
    ):
        admission.refuse(
            "orchestration_forbidden",
            "durable execution authority is stale or belongs to another Task",
        )
    return proof


def complete_cas(c: Any, ns: str, snapshot: Any, parent: Any, children: list[Any]) -> bool:
    """Linearize STOP observation and DB-time authority checks with the terminal CAS."""
    from psycopg.types.json import Jsonb

    from agent_storage.postgres.force_stop_signal import STOP_RECORDS

    expected = {str(snapshot.parent_task_id): {**parent, "parent": True}}
    expected.update({f["child_task_id"]: {**f, "parent": False} for f in children})
    stop = STOP_RECORDS.replace("%(sid)s", "t.active_segment_id")
    row = c.execute(
        """WITH expected AS (SELECT key::uuid AS task_id,value FROM jsonb_each(%(tasks)s::jsonb))
        UPDATE orchestration_runs SET status='completed',updated_at=clock_timestamp()
        WHERE deployment_namespace=%(namespace)s AND run_id=%(run)s
          AND current_plan_revision=%(revision)s AND status='synthesizing'
          AND NOT EXISTS (
            SELECT 1 FROM expected x LEFT JOIN agent_tasks t
              ON t.deployment_namespace=%(namespace)s AND t.task_id=x.task_id
            LEFT JOIN session_projections p ON p.deployment_namespace=t.deployment_namespace
              AND p.session_id=t.active_segment_id
            LEFT JOIN LATERAL (SELECT binding_digest,snapshot_json FROM task_binding_snapshots
              WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id
              ORDER BY binding_revision DESC LIMIT 1) b ON true
            LEFT JOIN LATERAL (SELECT CASE WHEN event_type='execution_authority_resolved'
                THEN payload ELSE payload->'effective_snapshot' END AS proof,
                CASE WHEN event_type='execution_authority_resolved' THEN payload->>'resolution'
                ELSE payload->>'decision' END AS decision
              FROM session_events WHERE deployment_namespace=t.deployment_namespace
                AND task_id=t.task_id AND session_id=t.active_segment_id
                AND event_type IN ('execution_authority_resolved','execution_authority_revalidated')
              ORDER BY task_sequence DESC LIMIT 1) a ON true
            WHERE t.task_id IS NULL OR t.active_segment_id::text<>x.value->>'session_id'
              OR b.binding_digest IS DISTINCT FROM x.value->>'binding_digest'
              OR p.status IS NULL OR ((x.value->>'parent')::boolean
                AND p.status IN ('completed','failed','cancelled'))
              OR (NOT (x.value->>'parent')::boolean AND p.status<>x.value->>'status')
              OR coalesce((b.snapshot_json#>>'{host_capability,grant_expires_at}')::timestamptz,
                '-infinity')<=clock_timestamp()
              OR coalesce(
                  (b.snapshot_json#>>'{host_capability,host_context,expires_at}')::timestamptz,
                '-infinity')<=clock_timestamp()
              OR a.decision IS NULL OR a.decision NOT IN ('allowed','narrowed')
              OR coalesce((a.proof->>'expires_at')::timestamptz,'-infinity')<=clock_timestamp()
              OR a.proof->>'source_authority_digest' IS DISTINCT FROM b.binding_digest
              OR (a.proof->'granted_authorities' ? 'agent.execute') IS NOT TRUE
              OR a.proof->>'agent_definition_snapshot_digest' IS DISTINCT FROM
                b.snapshot_json#>>'{agent_capability_ceiling,definition_snapshot_digest}'
              OR a.proof->>'policy_effective_digest' IS DISTINCT FROM
                b.snapshot_json->>'zebra_policy_digest'
              OR EXISTS ("""
        + stop
        + """))
          AND NOT EXISTS (SELECT 1 FROM artifact_payload_metadata a
            WHERE a.deployment_namespace=%(namespace)s AND a.artifact_id=ANY(%(artifacts)s::uuid[])
              AND (a.lifecycle_status<>'finalized' OR a.object_verified_at IS NULL
                OR a.retained_until<=clock_timestamp()))
          AND EXISTS (SELECT 1 FROM worker_leases l JOIN control_plane_epochs e
              ON e.deployment_namespace=l.deployment_namespace
            JOIN worker_task_budgets b ON b.deployment_namespace=l.deployment_namespace
              AND b.last_session_id=l.session_id
            WHERE l.deployment_namespace=%(namespace)s AND l.session_id=%(parent_sid)s
              AND b.task_id=%(parent_task)s AND b.binding_digest=%(parent_binding)s
              AND e.epoch=l.control_plane_epoch AND l.control_plane_epoch=%(epoch)s
              AND l.fencing_token=%(fence)s AND l.owner_instance_id=%(owner)s
              AND l.released_at IS NULL AND l.expires_at>clock_timestamp()
              AND b.deadline>clock_timestamp()) RETURNING run_id""",
        {
            "tasks": Jsonb(expected),
            "artifacts": [a["artifact_id"] for f in children for a in f["artifacts"]],
            "namespace": ns,
            "run": snapshot.run_ref,
            "revision": snapshot.plan_revision,
            "parent_sid": parent["session_id"],
            "parent_task": str(snapshot.parent_task_id),
            "parent_binding": snapshot.parent_binding_digest,
            "epoch": parent["fence"]["control_plane_epoch"],
            "fence": parent["fence"]["fencing_token"],
            "owner": parent["fence"]["owner_instance_id"],
        },
    ).fetchone()
    return row is not None
