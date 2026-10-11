"""Actual isolated Worker restart and canonical recovery, never fabricated execution."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from isolation import joint_preflight
from joint_acceptance import native_source_identity, validate_live_evidence
from joint_business_seed import validate_seed
from joint_fault_cases import verified_outputs
from scratch_topology import docker
from support import Config, E2EError, business_snapshot, task_binding
from terminal_probe import live_worker

SCHEMA = "zebra.joint-takeover.v1"
VIEW = """jsonb_build_object(
 'attempt',payload->'attempt_number','call',payload->'tool_call_id',
 'tool_name',payload->'tool_name','status',payload->'status',
 'facts',payload->'metadata'->'public_facts','reason',COALESCE(payload->'reason',payload->'metadata'->'reason'),
 'transport',payload->'metadata'->'transport_outcome','outcome',payload->'metadata'->'business_outcome',
 'output',payload->'output_id','phase',payload->'phase','refs',payload->'evidence_refs',
 'content',CASE WHEN event_type='public_output' THEN payload->'content' END,
 'meaningful',payload->'meaningful','basis',payload->'evidence_basis',
 'replaces',payload->'replaces_output_id','provider',payload->'provider',
 'request_hash',payload->'request_hash','stage',payload->'response_stage',
 'purpose',payload->'purpose','model_error',payload->'normalized_error',
 'repair_count',payload->'response_repair_count','fingerprint',payload->'call_fingerprint')"""


def takeover_prompt(marker: str, seed: Mapping[str, Any]) -> str:
    validate_seed(seed)
    if not re.fullmatch(r"ZEBRA_QA_SIMPLE_[a-f0-9]{32}", marker):
        raise E2EError("takeover_marker_invalid")
    return (
        f"只读核验 QA {seed['seed_id']}：先 events.search_history "
        f"source_id={seed['source_ids'][0]} "
        "limit=20，立即公开实际结果和覆盖范围。然后独立查询第二个来源，最后简短比较。"
        "不要修改订阅或业务数据，不读全文。不要重复已完成调用或先前里程碑；"
        "后台恢复不是新任务，不重置预算。不自行生成工具回执。"
        f"最终最后一段只放 {marker}。"
    )


def partials(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return verified_outputs(
        [{**row, "tool_call_id": row.get("call"), "output_id": row.get("output")} for row in rows]
    )


def native_execution(
    config: Config, task: str, run_id: str, deadline: float, *, include_effects: bool = False
) -> dict[str, Any]:
    """Two <=256 header windows, admitted public point bytes, exact lease/Task scalars."""
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_replay_headers import read_run_header

    scope = json.loads(Path(config.isolation_manifest).read_text())["namespace_id"]
    db = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    with db.connect_task_io(deadline=min(deadline, time.monotonic() + 2)) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        run = read_run_header(c, scope, TaskId(UUID(task)), run_id, None)
        if run.anchor is None or run.control_only:
            raise E2EError("takeover_run_not_canonical")
        prefix = c.execute(
            "SELECT event_id,event_type FROM session_events WHERE deployment_namespace=%s "
            "AND task_id=%s AND task_sequence<=%s ORDER BY task_sequence DESC LIMIT 256",
            (scope, task, run.start),
        ).fetchall()
        prepared = next((r for r in prefix if r["event_type"] == "task_prepared"), None)
        if prepared is None:
            raise E2EError("takeover_fresh_task_budget_not_found")
        budget = c.execute(
            "SELECT payload->'max_model_calls' AS max_model_calls,"
            "payload->'max_tool_calls' AS max_tool_calls FROM session_events "
            "WHERE deployment_namespace=%s AND event_id=%s",
            (scope, prepared["event_id"]),
        ).fetchone()
        headers = c.execute(
            "SELECT task_sequence,event_id,event_type FROM session_events "
            "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence BETWEEN %s AND %s "
            "ORDER BY task_sequence LIMIT 257",
            (scope, task, run.start, run.stop - 1 if run.stop else run.highwater),
        ).fetchall()
        if len(headers) > 256:
            raise E2EError("takeover_header_evidence_limit")
        rows, remaining = [], 1_048_576
        for header in headers:
            key = (scope, header["event_id"])
            where = " FROM session_events WHERE deployment_namespace=%s AND event_id=%s"
            size = c.execute(
                "SELECT octet_length((" + VIEW + ")::text) AS n" + where, key
            ).fetchone()
            if size is None or not 0 < size["n"] <= remaining:
                raise E2EError("takeover_point_evidence_limit")
            point = c.execute("SELECT " + VIEW + " AS data" + where, key).fetchone()
            if point is None:
                raise E2EError("takeover_point_missing")
            remaining -= size["n"]
            rows.append({**dict(header), "event_id": str(header["event_id"]), **point["data"]})
        state = c.execute(
            "SELECT t.active_segment_id,h.status,l.control_plane_epoch AS epoch,"
            "l.fencing_token AS token,l.owner_instance_id AS owner,l.checkpoint,"
            "l.released_at IS NOT NULL AS released,"
            "(l.released_at IS NULL AND l.expires_at>clock_timestamp()) AS active "
            "FROM agent_tasks t JOIN session_observation_headers h ON "
            "h.deployment_namespace=t.deployment_namespace "
            "AND h.session_id=t.active_segment_id::text "
            "LEFT JOIN worker_leases l ON l.deployment_namespace=t.deployment_namespace "
            "AND l.session_id=t.active_segment_id WHERE t.deployment_namespace=%s AND t.task_id=%s",
            (scope, task),
        ).fetchone()
        if state is None or state["token"] is None:
            raise E2EError("takeover_claim_not_observed")
        effects = []
        if include_effects:
            intents = [r["event_id"] for r in rows if r["event_type"] == "tool_execution_started"]
            effects = (
                c.execute(
                    "SELECT intent_event_id,status,attempt,CASE WHEN "
                    "octet_length(effect_identity->>'target_hash')=64 THEN "
                    "effect_identity->>'target_hash' END AS target_hash FROM effect_outbox "
                    "WHERE deployment_namespace=%s AND intent_event_id=ANY(%s::uuid[]) "
                    "AND effect_identity->>'tool_name'='sources.pause' LIMIT 257",
                    (scope, intents),
                ).fetchall()
                if intents
                else []
            )
            if len(effects) > 256:
                raise E2EError("authority_effect_evidence_limit")
    attempts = [r["attempt"] for r in rows if r["event_type"] == "harness_attempt_started"]
    return {
        "task_id": task,
        "run_id": run_id,
        "anchor_id": str(run.anchor.event_id),
        "segment": str(state["active_segment_id"]),
        "status": state["status"],
        "budget": budget,
        "attempt": max(attempts, default=0),
        "rows": rows,
        **(
            {
                "effects": [
                    {**dict(r), "intent_event_id": str(r["intent_event_id"])} for r in effects
                ]
            }
            if include_effects
            else {}
        ),
        "lease": {
            k: str(state[k]) if k == "epoch" else state[k]
            for k in ("epoch", "token", "owner", "checkpoint", "active", "released")
        },
    }


def process_identity(config: Config) -> dict[str, Any]:
    manifest = json.loads(Path(config.isolation_manifest).read_text())
    worker = manifest["containers"]["worker"]["id"]
    value = docker(["container", "inspect", worker, "--format", "{{json .State}}"], timeout=2)
    if len(value.encode()) > 8192:
        raise E2EError("takeover_process_evidence_limit")
    state = json.loads(value)
    if state.get("Running") is not True or type(state.get("Pid")) is not int or state["Pid"] <= 0:
        raise E2EError("takeover_worker_process_not_running")
    return {"started_at": state["StartedAt"], "host_pid": state["Pid"]}


def host_worker_restart(config: Config, task: str, run_id: str) -> int:
    """Explicit host-only QA authority; never accept a client-supplied container target."""
    from operator_sidecar import _restart_worker

    if (
        os.environ.get("ZEBRA_E2E_OPERATOR_MODE") != "host"
        or os.environ.get("ZEBRA_E2E_P1_FROZEN") != "1"
    ):
        raise E2EError("host_operator_explicit_frozen_authority_required")
    joint_preflight(config)
    manifest = json.loads(Path(config.isolation_manifest).read_text())
    identity = native_source_identity(config)
    if not identity or any(
        not isinstance(p, dict) or p.get("current_checkout_match") is not True
        for p in identity.values()
    ):
        raise E2EError("host_operator_latest_source_required")
    native = native_execution(config, task, run_id, time.monotonic() + 2)
    if native["lease"]["active"] is not True:
        raise E2EError("host_operator_active_canonical_run_required")
    process_identity(config)
    return _restart_worker(manifest["containers"]["worker"]["id"])


def host_business_snapshot(config: Config) -> str:
    """Fixed QA business tables, bounded native SQL deadline; no row bodies enter evidence."""
    from agent_storage.postgres.database import PostgresDatabase
    from operator_sidecar import DEFAULT_TABLES
    from psycopg.conninfo import conninfo_to_dict

    proof = joint_preflight(config)
    scope = str(proof["namespace_id"])
    if conninfo_to_dict(config.trench_database_dsn).get("dbname") != scope + "_trench":
        raise E2EError("host_operator_scratch_database_required")
    facts = {}
    with PostgresDatabase(
        config.trench_database_dsn, deployment_namespace=scope
    ).connect_task_io() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        for table in DEFAULT_TABLES.split(","):
            row = c.execute(
                "SELECT count(*) AS count,max(octet_length(body)) AS max_bytes,"
                "md5(COALESCE(string_agg(md5(body),'' ORDER BY body),'')) AS digest "
                f'FROM (SELECT to_jsonb(t)::text AS body FROM "{table}" t LIMIT 257) q'
            ).fetchone()  # Fixed repository table list, not caller input.
            if row is None:
                raise E2EError("host_operator_snapshot_missing")
            if row["count"] > 256 or (row["max_bytes"] or 0) > 32768:
                raise E2EError("host_operator_snapshot_evidence_limit")
            facts[table] = dict(row)
    return sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def validate_takeover(evidence: Mapping[str, Any], native: Mapping[str, Any]) -> None:
    validate_live_evidence(evidence)
    op = evidence.get("operator", {})
    before, after = op.get("before", {}), op.get("after", {})
    if (
        evidence.get("case_id") != "worker_takeover"
        or evidence.get("healthy_samples") != 0
        or op.get("schema_version") != SCHEMA
        or op.get("scope") != "actual_scratch_operator_restart"
        or op.get("provider_or_receipt_injection") is not False
        or op.get("restart_accepted") is not True
        or op.get("business_unchanged") is not True
        or any(
            op.get(k) != native.get(k) or before.get(k) != native.get(k)
            for k in ("task_id", "run_id")
        )
        or evidence.get("run_id") != native.get("run_id")
        or after != native
        or before.get("anchor_id") != native.get("anchor_id")
        or before.get("segment") != native.get("segment")
    ):
        raise E2EError("takeover_actual_restart_not_proven")
    old, new = op.get("process_before", {}), op.get("process_after", {})
    worker = op.get("worker_before", {})
    if (
        not old.get("started_at")
        or old.get("started_at") == new.get("started_at")
        or type(old.get("host_pid")) is not int
        or type(new.get("host_pid")) is not int
        or old["host_pid"] <= 0
        or new["host_pid"] <= 0
        or old["host_pid"] == new["host_pid"]
        or worker.get("coverage_complete") is not True
        or worker.get("execution_threads") != 1
        or type(worker.get("model_threads")) is not int
        or worker["model_threads"] < 1
    ):
        raise E2EError("takeover_actual_execution_or_process_not_proven")
    old_lease, new_lease = before["lease"], native["lease"]
    if (
        native.get("status") not in {"completed", "awaiting_turn"}
        or new_lease.get("active") is not False
    ):
        raise E2EError("takeover_terminal_cleanup_not_proven")
    if (
        old_lease.get("active") is not True
        or old_lease.get("epoch") != new_lease.get("epoch")
        or type(new_lease.get("token")) is not int
        or new_lease["token"] <= old_lease["token"]
        or new_lease["checkpoint"] < old_lease["checkpoint"]
        or type(native.get("attempt")) is not int
        or native["attempt"] < before["attempt"]
    ):
        raise E2EError("takeover_native_fence_or_attempt_regression")
    rows = native["rows"]
    positions = [r["task_sequence"] for r in rows]
    if (
        not 1 <= len(rows) <= 256
        or any(type(p) is not int or p < 0 for p in positions)
        or positions != sorted(set(positions))
        or rows[: len(before["rows"])] != before["rows"]
    ):
        raise E2EError("takeover_canonical_prefix_changed")
    budget = native["budget"]
    if budget != before.get("budget") or any(
        type(budget.get(k)) is not int or budget[k] <= 0
        for k in ("max_model_calls", "max_tool_calls")
    ):
        raise E2EError("takeover_budget_changed_or_unlimited")
    models = [
        r
        for r in rows
        if r["event_type"] == "model_response_received" and r.get("stage") != "public_expression"
    ]
    if not models or any(
        r.get("provider") not in {"deepseek", "openai", "openai-compatible"}
        or not re.fullmatch(r"[a-f0-9]{64}", r.get("request_hash") or "")
        or r.get("model_error") is not None
        for r in models
    ):
        raise E2EError("takeover_real_model_not_proven")
    calls = [r["call"] for r in rows if r["event_type"] == "tool_execution_started"]
    if any(
        type(r.get("repair_count") or 0) is not int or (r.get("repair_count") or 0) < 0
        for r in models
    ):
        raise E2EError("takeover_model_repair_count_invalid")
    requests = sum(
        r["event_type"] == "model_request_started" and r.get("purpose") != "public_expression"
        for r in rows
    ) + sum(r.get("repair_count") or 0 for r in models)
    if requests > budget["max_model_calls"] or len(calls) > budget["max_tool_calls"]:
        raise E2EError("takeover_global_run_budget_exceeded")
    if len(calls) != len(set(calls)) or any(not isinstance(c, str) or not c for c in calls):
        raise E2EError("takeover_duplicate_tools")
    outputs = [r for r in rows if r["event_type"] == "public_output"]
    if len({r["output"] for r in outputs}) != len(outputs) or any(not r["output"] for r in outputs):
        raise E2EError("takeover_duplicate_public_output")
    previous = {r["output"] for r in before["rows"] if r["event_type"] == "public_output"}
    covered = {ref for r in partials(before["rows"]) for ref in r.get("refs") or []}
    if not covered or any(
        r.get("phase") == "evidence"
        and covered.intersection(r.get("refs") or [])
        and r.get("replaces") not in previous
        for r in rows[len(before["rows"]) :]
    ):
        raise E2EError("takeover_repeated_or_missing_milestone")
    if sum(r["event_type"] == "answer_committed" for r in rows) != 1:
        raise E2EError("takeover_unique_final_missing")


def operate_takeover(config: Config, *, conversation_key: str, run_id: str) -> dict[str, Any]:
    from run_acceptance import worker_restart

    joint_preflight(config)
    mode = os.environ.get("ZEBRA_E2E_OPERATOR_MODE", "sidecar")
    if mode not in {"host", "sidecar"} or mode == "sidecar" and not config.operator_token:
        raise E2EError("takeover_operator_unconfigured")
    task, thread = task_binding(config, conversation_key=conversation_key, simple_slice=True)
    deadline = time.monotonic() + config.timeout_seconds
    snapshot = host_business_snapshot if mode == "host" else business_snapshot
    business = snapshot(config)
    while time.monotonic() < deadline:
        before = native_execution(config, task, run_id, deadline)
        if any(r["event_type"] == "answer_committed" for r in before["rows"]):
            raise E2EError("takeover_terminal_before_fault")
        model = [
            r
            for r in before["rows"]
            if r["event_type"] in {"model_request_started", "model_response_received"}
            and r.get("purpose") != "public_expression"
            and r.get("stage") != "public_expression"
        ]
        worker = live_worker(config, deadline)
        if (
            partials(before["rows"])
            and before["lease"]["active"] is True
            and model
            and model[-1]["event_type"] == "model_request_started"
            and worker.get("coverage_complete") is True
            and worker.get("execution_threads") == 1
            and worker.get("model_threads", 0) > 0
        ):
            break
        time.sleep(0.05)
    else:
        raise E2EError("takeover_admitted_model_operation_not_observed")
    old_process = process_identity(config)
    if mode == "host":
        host_worker_restart(config, task, run_id)
    else:
        worker_restart(config, task, run_id)
    new_process = process_identity(config)
    while time.monotonic() < deadline:
        after = native_execution(config, task, run_id, deadline)
        if after["lease"]["token"] > before["lease"]["token"]:
            break
        time.sleep(0.05)
    else:
        raise E2EError("takeover_new_claim_not_observed")
    if task_binding(config, conversation_key=conversation_key, simple_slice=True) != (task, thread):
        raise E2EError("takeover_task_binding_changed")
    return {
        "schema_version": SCHEMA,
        "scope": "actual_scratch_operator_restart",
        "provider_or_receipt_injection": False,
        "task_id": task,
        "run_id": run_id,
        "before": before,
        "after": after,
        "worker_before": worker,
        "process_before": old_process,
        "process_after": new_process,
        "restart_accepted": True,
        "business_unchanged": business == snapshot(config),
        "operator_mode": mode,
    }


def main() -> int:
    from run_acceptance import REQUIRED_ENV
    from support import load_config

    try:
        if os.environ.get("ZEBRA_E2E_P1_FROZEN") != "1":
            raise E2EError("takeover_latest_build_freeze_required")
        raw = sys.stdin.read(8193)
        if len(raw.encode()) > 8192:
            raise E2EError("takeover_operator_input_limit")
        inputs = json.loads(raw)
        if (
            set(inputs) != {"case_id", "conversation_key", "run_id"}
            or inputs.pop("case_id") != "worker_takeover"
        ):
            raise E2EError("takeover_operator_input_invalid")
        config = load_config(os.environ, REQUIRED_ENV)
        print(json.dumps({"status": "passed", **operate_takeover(config, **inputs)}))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": exc.code
                    if isinstance(exc, E2EError)
                    else "takeover_operator_unproven",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
