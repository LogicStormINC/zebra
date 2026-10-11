"""Actual scratch SQL faults; never inject providers, durable Events or browser frames."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from agent_core.contracts.public_output import PublicReadFacts
from isolation import joint_preflight
from joint_acceptance import native_source_identity, validate_live_evidence
from joint_business_seed import validate_seed
from support import Config, E2EError, business_snapshot, task_binding

FAULT_CASES = frozenset({"slow_execution", "partial_failure"})
OPERATOR_SCHEMA = "zebra.joint-sql-fault.v1"
POINT_FIELDS = """jsonb_build_object(
 'tool_call_id',payload->'tool_call_id','tool_name',payload->'tool_name',
 'status',payload->'status','facts',payload->'metadata'->'public_facts',
 'reason',payload->'metadata'->'reason','policy',payload->'public_output_policy',
 'output_id',payload->'output_id','phase',payload->'phase','refs',payload->'evidence_refs',
 'content',payload->'content','meaningful',payload->'meaningful',
 'basis',payload->'evidence_basis','provider',payload->'provider',
 'request_hash',payload->'request_hash','response_stage',payload->'response_stage',
 'normalized_error',payload->'normalized_error')"""
POINT_TYPES = frozenset(
    (
        "model_request_started model_response_received tool_execution_started "
        "tool_execution_completed tool_execution_failed public_output answer_committed"
    ).split()
)


def fault_prompt(case_id: str, marker: str, seed: Mapping[str, Any]) -> str:
    if case_id not in FAULT_CASES:
        raise E2EError("fault_case_executor_unimplemented")
    validate_seed(seed)
    if not re.fullmatch(r"ZEBRA_QA_SIMPLE_[a-f0-9]{32}", marker):
        raise E2EError("fault_marker_invalid")
    return (
        f"只读 QA {seed['seed_id']}：先用 events.search_history 查询 source_id="
        f"{seed['source_ids'][0]}，limit=20，不读全文。先公开已确认事实及本页覆盖范围。"
        f"第一步完成后再查询 source_id={seed['source_ids'][1]}，limit=20。"
        + (
            "第二步同时并行调用 sources.list；其来源事实返回后立即报告，不等历史查询结束。"
            if case_id == "slow_execution"
            else "第二步可能真实超时；不要自动重复失败调用。"
        )
        + "不要修改订阅或业务数据。等待不代表成功；失败时保留先前已确认结果，"
        "明确失败边界，不编造第二页或完整覆盖。不要自行生成系统回执。"
        f"最终简短总结最后一段只放验收标记 {marker}。"
    )


def native_fault_points(config: Config, conversation_key: str, run_id: str) -> dict[str, Any]:
    """<=256 indexed Run headers, then size-admitted public scalar point reads."""
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_replay_headers import read_run_header

    task, thread = task_binding(config, conversation_key=conversation_key, simple_slice=True)
    manifest = json.loads(Path(config.isolation_manifest).read_text())
    scope = manifest["namespace_id"]
    db = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    points, remaining = [], 1_048_576
    with db.connect_task_io(deadline=time.monotonic() + 2) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        header = read_run_header(c, scope, TaskId(UUID(task)), run_id, None)
        if header.anchor is None or header.control_only:
            raise E2EError("fault_run_not_canonical")
        rows = c.execute(
            "SELECT event_id,event_type,task_sequence FROM session_events "
            "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence BETWEEN %s AND %s "
            "ORDER BY task_sequence LIMIT 257",
            (scope, task, header.start, header.stop - 1 if header.stop else header.highwater),
        ).fetchall()
        if len(rows) > 256:
            raise E2EError("fault_header_evidence_limit")
        for row in rows:
            if row["event_type"] not in POINT_TYPES:
                continue
            where = " FROM session_events WHERE deployment_namespace=%s AND event_id=%s"
            keys = (scope, row["event_id"])
            size = c.execute(
                "SELECT octet_length((" + POINT_FIELDS + ")::text) AS n" + where, keys
            ).fetchone()
            if size is None or not 0 < size["n"] <= remaining:
                raise E2EError("fault_point_evidence_limit")
            value = c.execute("SELECT " + POINT_FIELDS + " AS data" + where, keys).fetchone()
            if value is None:
                raise E2EError("fault_point_source_missing")
            remaining -= size["n"]
            points.append({**dict(row), "event_id": str(row["event_id"]), **value["data"]})
    return {
        "task_id": task,
        "host_thread": thread,
        "run_id": run_id,
        "scope": "canonical_run_headers_and_public_points",
        "points": points,
    }


def verified_outputs(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    receipts = {
        p.get("tool_call_id"): p
        for p in points
        if p["event_type"] == "tool_execution_completed" and p.get("status") == "executed"
    }
    outputs = []
    for output in points:
        if (
            output["event_type"] != "public_output"
            or output.get("meaningful") is not True
            or output.get("basis") != "verified_result"
        ):
            continue
        for ref in output.get("refs") or []:
            receipt = receipts.get(ref)
            if receipt is None or receipt["task_sequence"] >= output["task_sequence"]:
                continue
            try:
                fact = PublicReadFacts.model_validate(receipt.get("facts"))
            except ValueError:
                continue
            if fact.summary in (output.get("content") or ""):
                outputs.append(
                    {**output, "receipt_sequence": receipt["task_sequence"], "receipt_call_id": ref}
                )
                break
    return outputs


def validate_fault(evidence: Mapping[str, Any], native: Mapping[str, Any]) -> None:
    validate_live_evidence(evidence)
    case_id, operation = evidence.get("case_id"), evidence.get("operator", {})
    points = native.get("points", [])
    sequences = [p["task_sequence"] for p in points]
    if (
        case_id not in FAULT_CASES
        or native.get("run_id") != evidence.get("run_id")
        or native.get("scope") != "canonical_run_headers_and_public_points"
        or not points
        or len(points) > 256
        or sequences != sorted(set(sequences))
    ):
        raise E2EError("fault_source_identity_invalid")
    if (
        operation.get("schema_version") != OPERATOR_SCHEMA
        or operation.get("scope") != "actual_scratch_business_sql_lock"
        or operation.get("provider_or_receipt_injection") is not False
        or operation.get("case_id") != case_id
        or operation.get("task_id") != native["task_id"]
        or operation.get("run_id") != native["run_id"]
        or any(
            operation.get(key) is not True
            for key in (
                "blocked_on_business_sql",
                "holder_closed",
                "backend_gone",
                "business_unchanged",
            )
        )
    ):
        raise E2EError("fault_operator_not_proven")
    models = [
        p
        for p in points
        if p["event_type"] == "model_response_received"
        and p.get("response_stage") != "public_expression"
    ]
    if not models or any(
        p.get("provider") not in {"deepseek", "openai", "openai-compatible"}
        or not re.fullmatch(r"[a-f0-9]{64}", p.get("request_hash") or "")
        or p.get("normalized_error") is not None
        for p in models
    ):
        raise E2EError("fault_real_model_not_proven")
    finals = [p for p in points if p["event_type"] == "answer_committed"]
    call_id = operation.get("target_call_id")
    starts = [
        p
        for p in points
        if p["event_type"] == "tool_execution_started" and p.get("tool_call_id") == call_id
    ]
    terminals = [
        p
        for p in points
        if p["event_type"] in {"tool_execution_completed", "tool_execution_failed"}
        and p.get("tool_call_id") == call_id
    ]
    if (
        len(finals) != 1
        or len(starts) != 1
        or len(terminals) != 1
        or starts[0]["tool_name"] != "events.search_history"
        or operation.get("started_sequence") != starts[0]["task_sequence"]
        or operation.get("terminal_sequence") != terminals[0]["task_sequence"]
        or not operation["armed_after_sequence"]
        < starts[0]["task_sequence"]
        < terminals[0]["task_sequence"]
        < finals[0]["task_sequence"]
    ):
        raise E2EError("fault_operation_window_unproven")
    outputs = verified_outputs(points)
    initial = [p for p in outputs if p["task_sequence"] <= operation["armed_after_sequence"]]
    if not initial:
        raise E2EError("fault_usable_partial_missing")
    required = [initial[0]]
    if case_id == "slow_execution":
        waits = [
            p
            for p in points
            if p["event_type"] == "public_output"
            and p.get("phase") == "waiting"
            and p.get("meaningful") is False
            and starts[0]["task_sequence"] < p["task_sequence"] < terminals[0]["task_sequence"]
        ]
        flushed = [
            p
            for p in outputs
            if starts[0]["task_sequence"]
            < p["receipt_sequence"]
            < p["task_sequence"]
            < terminals[0]["task_sequence"]
            and p["receipt_call_id"] != call_id
        ]
        if not waits or not flushed or terminals[0].get("status") != "executed":
            raise E2EError("fault_silence_flush_or_wait_unproven")
        required += [waits[0], flushed[0]]
    else:
        recovery = [
            p
            for p in points
            if p["event_type"] == "public_output"
            and p.get("phase") == "recovery"
            and call_id in (p.get("refs") or [])
            and p.get("meaningful") is False
            and terminals[0]["task_sequence"] < p["task_sequence"] < finals[0]["task_sequence"]
        ]
        if (
            terminals[0]["event_type"] != "tool_execution_failed"
            or terminals[0].get("reason") != "timeout"
            or not recovery
        ):
            raise E2EError("fault_failure_boundary_unproven")
        required.append(recovery[0])
    frames = {p.get("output_id"): p for p in evidence["frames"] if p.get("type") == "public_output"}
    visible = {
        p.get("output_id")
        for p in evidence.get("fault_visibility", [])
        if p.get("before_terminal") is True and p.get("before_final_receipt") is True
    }
    for output in required:
        frame = frames.get(output["output_id"], {})
        if (
            output["output_id"] not in visible
            or frame.get("event_id") != output["event_id"]
            or frame.get("content_sha256") != sha256(output["content"].encode()).hexdigest()
        ):
            raise E2EError("fault_canonical_output_not_visible")


def operate_fault(
    config: Config, *, case_id: str, conversation_key: str, run_id: str
) -> dict[str, Any]:
    from agent_storage.postgres.database import PostgresDatabase
    from psycopg.conninfo import conninfo_to_dict

    if case_id not in FAULT_CASES:
        raise E2EError("fault_case_executor_unimplemented")
    proof = joint_preflight(config)
    scope = cast(str, proof["namespace_id"])
    params = conninfo_to_dict(config.trench_database_dsn)
    if params.get("dbname") != scope + "_trench":
        raise E2EError("fault_business_database_not_isolated")
    before = business_snapshot(config)  # Reuse the existing read-only operator sidecar.
    deadline = time.monotonic() + config.timeout_seconds
    initial = None
    while time.monotonic() < deadline:
        native = native_fault_points(config, conversation_key, run_id)
        outputs = verified_outputs(native["points"])
        if outputs:
            initial = outputs[0]
            break
        if any(p["event_type"] == "answer_committed" for p in native["points"]):
            raise E2EError("fault_first_receipt_not_observed")
        time.sleep(0.05)
    if initial is None:
        raise E2EError("fault_first_receipt_timeout")
    policies = [p["policy"] for p in native["points"] if p.get("policy")]
    if case_id == "slow_execution" and (not policies or not 0 < policies[0]["wait_seconds"] < 8):
        raise E2EError("fault_frozen_wait_must_precede_host_timeout")
    db = PostgresDatabase(config.trench_database_dsn, deployment_namespace=scope)
    result: dict[str, Any] = {
        "schema_version": OPERATOR_SCHEMA,
        "scope": "actual_scratch_business_sql_lock",
        "provider_or_receipt_injection": False,
        "case_id": case_id,
        "task_id": native["task_id"],
        "run_id": run_id,
        "armed_after_sequence": max(p["task_sequence"] for p in native["points"]),
        "blocked_on_business_sql": False,
    }
    holder = db.connect_task_io()
    try:
        pid = holder.info.backend_pid
        holder.execute("LOCK TABLE events IN ACCESS EXCLUSIVE MODE NOWAIT")
        expires = min(deadline, time.monotonic() + (8 if case_id == "slow_execution" else 15))
        while time.monotonic() < expires:
            with db.connect_task_io(deadline=expires) as observe:
                observe.execute("SET TRANSACTION READ ONLY")
                blocked = observe.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                    "AND %s=ANY(pg_blocking_pids(pid))) AS blocked",
                    (pid,),
                ).fetchone()
                result["blocked_on_business_sql"] |= bool(blocked and blocked["blocked"])
            current = native_fault_points(config, conversation_key, run_id)
            if (current["task_id"], current["host_thread"]) != (
                native["task_id"],
                native["host_thread"],
            ):
                raise E2EError("fault_task_binding_changed")
            starts = [
                p
                for p in current["points"]
                if p["event_type"] == "tool_execution_started"
                and p.get("tool_name") == "events.search_history"
                and p["task_sequence"] > result["armed_after_sequence"]
            ]
            if len(starts) > 1:
                raise E2EError("fault_target_ambiguous")
            if starts:
                target = starts[0]
                result.update(
                    target_call_id=target["tool_call_id"], started_sequence=target["task_sequence"]
                )
                ended = [
                    p
                    for p in current["points"]
                    if p.get("tool_call_id") == target["tool_call_id"]
                    and p["event_type"] in {"tool_execution_completed", "tool_execution_failed"}
                ]
                waited = any(
                    p["event_type"] == "public_output"
                    and p.get("phase") == "waiting"
                    and target["task_sequence"] < p["task_sequence"]
                    for p in current["points"]
                )
                if result["blocked_on_business_sql"] and (
                    case_id == "slow_execution" and waited or case_id == "partial_failure" and ended
                ):
                    if ended:
                        result["terminal_sequence"] = ended[0]["task_sequence"]
                    break
            time.sleep(0.05)
        else:
            raise E2EError("fault_actual_operation_not_observed")
    finally:
        primary = sys.exception()
        try:
            holder.close()
        except BaseException as cleanup:
            if primary is None:
                raise
            primary.add_note(f"fault holder cleanup failed: {type(cleanup).__name__}")
    result["holder_closed"] = holder.closed
    cleanup_deadline = time.monotonic() + 1
    while time.monotonic() < cleanup_deadline:
        with db.connect_task_io(deadline=cleanup_deadline) as observe:
            observe.execute("SET TRANSACTION READ ONLY")
            gone = observe.execute(
                "SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s) AS gone", (pid,)
            ).fetchone()
        if gone and gone["gone"]:
            result["backend_gone"] = True
            break
        time.sleep(0.01)
    else:
        raise E2EError("fault_lock_backend_survived")
    while "terminal_sequence" not in result and time.monotonic() < deadline:
        current = native_fault_points(config, conversation_key, run_id)
        ended = [
            p
            for p in current["points"]
            if p.get("tool_call_id") == result["target_call_id"]
            and p["event_type"] in {"tool_execution_completed", "tool_execution_failed"}
        ]
        if ended:
            result["terminal_sequence"] = ended[0]["task_sequence"]
            break
        time.sleep(0.05)
    if "terminal_sequence" not in result:
        raise E2EError("fault_terminal_not_observed")
    result["business_unchanged"] = before == business_snapshot(config)
    return result


def run_fault_case(
    config: Config,
    environment: Mapping[str, str],
    evidence_dir: Path,
    *,
    case_id: str,
    seed: Mapping[str, Any],
) -> dict[str, Any]:
    if environment.get("ZEBRA_E2E_P1_FROZEN") != "1":
        raise E2EError("fault_latest_build_freeze_required")
    joint_preflight(config)
    identity = native_source_identity(config)
    if not identity or any(
        not isinstance(p, dict) or p.get("current_checkout_match") is not True
        for p in identity.values()
    ):
        raise E2EError("fault_latest_source_not_deployed")
    marker = "ZEBRA_QA_SIMPLE_" + uuid4().hex
    prompt = fault_prompt(case_id, marker, seed)
    script = (
        Path(__file__).resolve().parents[3].parent
        / "Trench/toc-frontend/scripts/strategy-joint-acceptance.mjs"
    )
    inputs = {
        "case_id": case_id,
        "prompt": prompt,
        "expected": marker,
        "fault_script": str(Path(__file__).resolve()),
        "base_url": config.bff_url,
        "cookie": config.session_cookie,
        "timeout_ms": config.timeout_seconds * 1000,
        "python": sys.executable,
        "guard_script": str(Path(__file__).with_name("run_acceptance.py")),
        "cleanup_script": str(Path(__file__).with_name("terminal_probe.py")),
        "evidence_dir": str(evidence_dir.resolve()),
        "tls_spki": environment.get("ZEBRA_E2E_TLS_SPKI", ""),
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [environment.get("ZEBRA_E2E_NODE", "node"), str(script)],
        cwd=script.parent.parent,
        env=dict(environment),
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
        timeout=config.timeout_seconds + 60,
        check=False,
    )
    if completed.returncode != 0:
        raise E2EError("fault_real_browser_executor_failed")
    path = evidence_dir / (case_id.replace("_", "-") + ".json")
    if path.stat().st_size > 1_048_576:
        raise E2EError("fault_browser_evidence_limit")
    browser = json.loads(path.read_text())
    native = native_fault_points(config, browser["conversation_key"], browser["run_id"])
    validate_fault(browser, native)
    if native_source_identity(config) != identity:
        raise E2EError("fault_source_changed_during_run")
    return {
        "case_id": case_id,
        "status": "slice_passed",
        "source_identity": identity,
        "native": native,
        "browser": browser,
        "fault": case_id,
        "healthy_samples": 0,
        "full_goal_passed": False,
    }


def main() -> int:
    from run_acceptance import REQUIRED_ENV
    from support import load_config

    try:
        if os.environ.get("ZEBRA_E2E_P1_FROZEN") != "1":
            raise E2EError("fault_latest_build_freeze_required")
        raw = sys.stdin.read(8193)
        if len(raw.encode()) > 8192:
            raise E2EError("fault_operator_input_limit")
        argument = json.loads(raw)
        if set(argument) != {"case_id", "conversation_key", "run_id"}:
            raise E2EError("fault_operator_input_invalid")
        config = load_config(os.environ, REQUIRED_ENV)
        result = operate_fault(config, **argument)
        print(json.dumps({"status": "passed", **result}))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "reason": "fault_operator_unproven"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
