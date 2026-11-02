"""Short atomic completion observation, immutable receipt and final run CAS."""

from typing import Any

from agent_core.domain.subagents import CompletionGateReceipt
from agent_orchestration.application.completion_gate import GateEvaluation
from agent_orchestration.application.orchestration_admission import digest
from agent_orchestration.application.orchestration_completion_gate import (
    evaluate_durable_completion,
)
from agent_orchestration.domain.orchestration import OrchestrationPlanSnapshot
from psycopg.types.json import Jsonb

from agent_storage.postgres import orchestration_admission_queries as admission
from agent_storage.postgres.orchestration_gate_queries import (
    child_facts,
    complete_cas,
    parent_boundary,
)
from agent_storage.postgres.work_unit import postgres_work_unit


def complete_run(store: Any, run_ref: str) -> GateEvaluation:
    """Only this path may consume production completion facts; no GateInput argument."""
    ns = store.deployment_namespace
    with postgres_work_unit(store._database), store._database.connect() as c:
        c.execute("SET LOCAL lock_timeout='500ms'")
        c.execute("SET LOCAL statement_timeout='3000ms'")
        # Parent validator locks parent before run, matching admission lock order.
        preview = store.get_snapshot(run_ref)
        if preview is None:
            admission.refuse("unknown_run", "missing plan")
        authorize = store._gate_authorize
        if authorize is None:
            admission.refuse(
                "gate_authority_unavailable", "current published parent authority required"
            )
        parent = parent_boundary(c, ns, preview)
        current_policy = authorize(c, preview)
        run = c.execute(
            "SELECT current_plan_revision,status FROM orchestration_runs "
            "WHERE deployment_namespace=%s AND run_id=%s FOR UPDATE",
            (ns, run_ref),
        ).fetchone()
        if run is None or run["current_plan_revision"] != preview.plan_revision:
            admission.refuse("revision_conflict", "completion revision is no longer current")
        row = c.execute(
            "SELECT snapshot_json FROM orchestration_plan_revisions "
            "WHERE deployment_namespace=%s AND run_id=%s AND plan_revision=%s",
            (ns, run_ref, preview.plan_revision),
        ).fetchone()
        snapshot = OrchestrationPlanSnapshot.model_validate(row["snapshot_json"])
        if snapshot != preview:
            admission.refuse("revision_conflict", "frozen completion plan changed")
        nodes = c.execute(
            "SELECT node_key,status,child_task_id FROM orchestration_nodes "
            "WHERE deployment_namespace=%s AND run_id=%s AND plan_revision=%s "
            "ORDER BY node_key FOR UPDATE",
            (ns, run_ref, snapshot.plan_revision),
        ).fetchall()
        states = {n["node_key"]: n for n in nodes}
        if set(states) != {n.node_key for n in snapshot.nodes} or any(
            n["status"] not in {"completed", "failed", "cancelled", "skipped"} for n in nodes
        ):
            admission.refuse("nodes_still_running", "exact current nodes must be terminal")
        if run["status"] not in {"running", "completed"}:
            admission.refuse("run_not_running", "run no longer permits completion")
        children = [child_facts(c, ns, snapshot, n, states[n.node_key]) for n in snapshot.nodes]
        frozen = c.execute(
            "SELECT policy FROM orchestration_completion_policies WHERE deployment_namespace=%s "
            "AND run_id=%s AND plan_revision=%s",
            (ns, run_ref, snapshot.plan_revision),
        ).fetchone()
        policy = None if frozen is None else frozen["policy"]
        if policy is not None and policy != current_policy:
            admission.refuse(
                "gate_policy_conflict", "frozen policy differs from current bound Version"
            )
        facts = {
            "schema": "zebra.orchestration-completion-observation/1",
            "run_ref": run_ref,
            "plan_revision": snapshot.plan_revision,
            "snapshot_digest": digest(snapshot.model_dump(mode="json")),
            "parent": parent,
            "children": children,
            "policy": policy,
        }
        evaluation = evaluate_durable_completion(
            run_ref,
            policy=policy,
            completion_strategy=snapshot.completion_strategy,
            children=children,
        )
        input_digest = digest(facts)
        payload = {
            "passed": evaluation.passed,
            "blocked": evaluation.blocked,
            "reason_code": evaluation.reason_code,
            "receipts": [r.model_dump(mode="json") for r in evaluation.receipts],
        }
        previous = c.execute(
            "SELECT facts,evaluation FROM orchestration_completion_observations "
            "WHERE deployment_namespace=%s AND run_id=%s AND plan_revision=%s AND input_digest=%s",
            (ns, run_ref, snapshot.plan_revision, input_digest),
        ).fetchone()
        if previous is not None:
            if previous["facts"] != facts or any(
                previous["evaluation"][k] != payload[k]
                for k in ("passed", "blocked", "reason_code")
            ):
                admission.refuse("gate_receipt_conflict", "immutable observation differs")
            evaluation = GateEvaluation(
                tuple(
                    CompletionGateReceipt.model_validate(r)
                    for r in previous["evaluation"]["receipts"]
                ),
                previous["evaluation"]["passed"],
                previous["evaluation"]["blocked"],
                previous["evaluation"]["reason_code"],
            )
        else:
            c.execute(
                "INSERT INTO orchestration_completion_observations "
                "(deployment_namespace,run_id,plan_revision,input_digest,facts,evaluation) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (ns, run_ref, snapshot.plan_revision, input_digest, Jsonb(facts), Jsonb(payload)),
            )
        # Fresh post-observation clock/STOP/current-authority check immediately
        # before terminal CAS; all identity/release locks remain held.
        for node, original in zip(snapshot.nodes, children, strict=True):
            if child_facts(c, ns, snapshot, node, states[node.node_key]) != original:
                admission.refuse(
                    "gate_child_conflict", "child observations changed before completion"
                )
        parent_boundary(c, ns, snapshot)
        if authorize(c, snapshot) != current_policy:
            admission.refuse("gate_policy_conflict", "current policy changed during completion")
        if evaluation.passed and run["status"] != "completed":
            c.execute(
                "UPDATE orchestration_runs SET status='synthesizing' "
                "WHERE deployment_namespace=%s AND run_id=%s AND status='running'",
                (ns, run_ref),
            )
            if not complete_cas(c, ns, snapshot, parent, children):
                admission.refuse(
                    "gate_receipt_conflict", "current STOP/time/authority terminal CAS failed"
                )
        return evaluation


def read_receipt(
    store: Any, run_ref: str, revision: int, input_digest: str
) -> dict[str, Any] | None:
    """Exact original observation only; reading it never authorizes completion."""
    with store._database.connect() as c:
        row = c.execute(
            "SELECT input_digest,facts,evaluation,created_at "
            "FROM orchestration_completion_observations "
            "WHERE deployment_namespace=%s AND run_id=%s AND plan_revision=%s AND input_digest=%s",
            (store.deployment_namespace, run_ref, revision, input_digest),
        ).fetchone()
    return None if row is None else dict(row)
