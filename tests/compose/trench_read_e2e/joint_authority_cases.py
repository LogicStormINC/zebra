"""Real scratch cancel/approval/target denial/unconfirmed write; no receipt injection."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from isolation import joint_preflight
from joint_acceptance import validate_live_evidence
from joint_business_seed import validate_seed
from joint_worker_takeover import native_execution
from support import (
    Config,
    E2EError,
    cookie_headers,
    join_url,
    json_object,
    obtain_grant,
    request,
    require_status,
    task_binding,
)
from terminal_probe import COUNTERS, live_worker

SUBCASES = frozenset({"cancel", "approval", "scope_denial", "unknown_write_receipt"})
SCHEMA = "zebra.joint-authority.v1"


def authority_prompt(subcase: str, marker: str, seed: Mapping[str, Any]) -> str:
    validate_seed(seed)
    if subcase not in SUBCASES or not re.fullmatch(r"ZEBRA_QA_SIMPLE_[a-f0-9]{32}", marker):
        raise E2EError("authority_case_or_marker_invalid")
    first = (
        f"核验 QA {seed['seed_id']}：先 events.search_history source_id={seed['source_ids'][0]} "
        "limit=20，只读摘要，立即公开实际事实和覆盖范围。"
    )
    second = {
        "cancel": "再独立查询第二来源并简短分析，支持真实取消，不生成取消或完成回执。",
        "scope_denial": "再独立查询第二来源并简短分析；仅做只读工具调用。",
        "approval": "随后仅提议 command.run argv=['curl','--version']，不要绕过现有审批。"
        "这不是网络下载；审批拒绝则不要执行或生成成功回执。",
        "unknown_write_receipt": f"随后仅一次 sources.pause source_id={seed['source_ids'][0]}。"
        "这是我明确授权的隔离 QA 来源。HTTP 200 不等于权威写回执；"
        "未确认结果要公开不确定性，不自动重试或宣称已完成。",
    }[subcase]
    return first + second + f"若正常完成，最后一段仅放 {marker}；取消/拒绝不编造 Final。"


def validate_authority(evidence: Mapping[str, Any], native: Mapping[str, Any]) -> None:
    subcase, op = evidence.get("authority_subcase"), evidence.get("operator", {})
    if (
        subcase not in SUBCASES
        or evidence.get("case_id") != "authority"
        or evidence.get("healthy_samples") != 0
        or op.get("schema_version") != SCHEMA
        or op.get("scope") != "actual_scratch_authority_http_and_native_pg"
        or op.get("provider_or_receipt_injection") is not False
        or op.get("action_accepted") is not True
        or op.get("subcase") != subcase
        or op.get("native") != native
        or evidence.get("run_id") != native.get("run_id")
        or any(op.get(k) != native.get(k) for k in ("task_id", "run_id"))
    ):
        raise E2EError("authority_native_identity_unproven")
    rows = native.get("rows", [])
    positions = [r["task_sequence"] for r in rows]
    if (
        not 1 <= len(rows) <= 256
        or any(type(p) is not int or p < 0 for p in positions)
        or positions != sorted(set(positions))
    ):
        raise E2EError("authority_source_window_invalid")
    worker = native.get("worker", {})
    if (
        native.get("lease", {}).get("released") is not True
        or worker.get("coverage_complete") is not True
        or any(type(worker.get(k)) is not int or worker[k] != 0 for k in COUNTERS)
    ):
        raise E2EError("authority_terminal_cleanup_unproven")
    finals = [r for r in rows if r["event_type"] == "answer_committed"]
    if subcase in {"cancel", "approval"}:
        frames = evidence.get("frames", [])
        cursors = [f.get("cursor") for f in frames]
        elapsed = evidence.get("terminal_observed_to_cleanup_ms")
        if (
            evidence.get("scope") != "real_scratch_host_browser_sse"
            or evidence.get("fixture_routes") is not False
            or evidence.get("post_count") != 1
            or evidence.get("admission_terminal") is not False
            or evidence.get("stream_open_before_terminal") is not True
            or finals
            or evidence.get("final_count") != 0
            or not 1 <= len(frames) <= 256
            or any(type(c) is not int or c < 1 for c in cursors)
            or cursors != sorted(set(cursors))
            or elapsed is None
            or type(elapsed) not in {int, float}
            or not 0 <= elapsed <= 5000
            or evidence.get("cleanup", {}).get("browser_closed") is not True
        ):
            raise E2EError("authority_real_nonanswer_terminal_unproven")
    else:
        validate_live_evidence(evidence)
        if len(finals) != 1:
            raise E2EError("authority_unique_final_unproven")
    if subcase == "cancel":
        cancelled = [r for r in rows if r["event_type"] in {"session_cancelled", "turn_cancelled"}]
        before = op.get("worker_before", {})
        if (
            len(cancelled) != 1
            or native.get("status") not in {"cancelled", "awaiting_turn"}
            or before.get("coverage_complete") is not True
            or before.get("execution_threads") != 1
            or type(before.get("model_threads")) is not int
            or before["model_threads"] < 1
            or not op.get("armed_sequence", -1) < cancelled[0]["task_sequence"]
            or any(
                r["task_sequence"] > cancelled[0]["task_sequence"]
                and r["event_type"]
                in {
                    "model_response_received",
                    "public_output",
                    "tool_execution_started",
                    "tool_execution_completed",
                    "tool_execution_failed",
                }
                for r in rows
            )
        ):
            raise E2EError("authority_actual_cancel_or_no_late_publication_unproven")
    elif subcase == "approval":
        pending = [r for r in rows if r["event_type"] == "approval_requested"]
        rejected = [r for r in rows if r["event_type"] == "approval_rejected"]
        visible = evidence.get("approval_visibility", {})
        call = op.get("target_call_id")
        if (
            len(pending) != 1
            or len(rejected) != 1
            or native.get("status") != "failed"
            or op.get("decision") != "reject"
            or not call
            or pending[0].get("call") != call
            or rejected[0].get("call") != call
            or not re.fullmatch(r"[a-f0-9]{64}", pending[0].get("fingerprint") or "")
            or pending[0]["fingerprint"] != rejected[0].get("fingerprint")
            or pending[0]["task_sequence"] >= rejected[0]["task_sequence"]
            or visible.get("tool_call_id") != call
            or visible.get("call_fingerprint") != pending[0]["fingerprint"]
            or visible.get("before_decision") is not True
            or not visible.get("screenshot")
            or any(
                r.get("call") == call and r["event_type"].startswith("tool_execution_")
                for r in rows
            )
        ):
            raise E2EError("authority_exact_approval_boundary_unproven")
    elif subcase == "scope_denial":
        if (
            op.get("http_statuses") not in ([404, 200, 401], [403, 200, 401])
            or op.get("replay_counts") != [0, 0, 1, 1]
            or op.get("same_grant_reused") is not True
            or op.get("target_run_changed") is not True
        ):
            raise E2EError("authority_target_before_atomic_consume_unproven")
    else:
        call = op.get("target_call_id")
        starts = [
            r
            for r in rows
            if r["event_type"] == "tool_execution_started" and r.get("tool_name") == "sources.pause"
        ]
        ended = [
            r
            for r in rows
            if r.get("call") == call
            and r["event_type"] in {"tool_execution_failed", "tool_execution_completed"}
        ]
        effects = native.get("effects", [])
        if (
            not call
            or len(starts) != 1
            or starts[0].get("call") != call
            or len(ended) != 1
            or ended[0]["event_type"] != "tool_execution_failed"
            or ended[0].get("reason") != "host_effect_unconfirmed"
            or ended[0].get("transport") != "returned"
            or ended[0].get("outcome") != "unknown"
            or not starts[0]["task_sequence"]
            < ended[0]["task_sequence"]
            < finals[0]["task_sequence"]
            or op.get("source_before") != "active"
            or op.get("source_after") != "paused"
            or not re.fullmatch(r"[a-f0-9]{16}000000000000000[01]", op.get("source_id") or "")
            or len(effects) != 1
            or effects[0].get("intent_event_id") != starts[0]["event_id"]
            or effects[0].get("status") != "uncertain"
            or effects[0].get("attempt") != 1
            or effects[0].get("target_hash")
            != sha256(
                json.dumps(
                    {"source_id": op["source_id"]},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
        ):
            raise E2EError("authority_real_unconfirmed_write_unproven")
        recovery = [
            r
            for r in rows
            if r["event_type"] == "public_output"
            and r.get("phase") == "recovery"
            and call in (r.get("refs") or [])
            and ended[0]["task_sequence"] < r["task_sequence"] < finals[0]["task_sequence"]
        ]
        if not any(
            v.get("output_id") == r["output"]
            and v.get("before_terminal") is True
            and v.get("before_final_receipt") is True
            and v.get("content_sha256") == sha256(r["content"].encode()).hexdigest()
            for r in recovery
            for v in evidence.get("fault_visibility", [])
        ):
            raise E2EError("authority_unknown_write_not_publicly_visible")


def validate_authority_matrix(cases: Mapping[str, Any]) -> None:
    if set(cases) != SUBCASES:
        raise E2EError("authority_all_four_actual_subcases_required")
    for subcase, case in cases.items():
        if case["browser"].get("authority_subcase") != subcase:
            raise E2EError("authority_matrix_subcase_substitution")
        validate_authority(case["browser"], case["native"])


def native_authority(config: Config, task: str, run: str, deadline: float) -> dict[str, Any]:
    native = native_execution(config, task, run, deadline, include_effects=True)
    native["worker"] = live_worker(config, deadline)
    return native


def scope_denial(config: Config, task: str, thread: str, run: str) -> dict[str, Any]:
    from agent_storage.postgres.database import PostgresDatabase

    grant = obtain_grant(config, thread, run)
    # Decode only the index key of the actual broker JWT, never synthesize/verify authority here.
    payload = grant.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    if not all(isinstance(claims.get(k), str) and claims[k] for k in ("iss", "jti")):
        raise E2EError("authority_actual_grant_index_missing")
    namespace = json.loads(Path(config.isolation_manifest).read_text())["namespace_id"]
    db = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=namespace)
    counts, statuses = [], []
    wrong_run = str(uuid4())
    paths = [
        f"/agui/threads/{quote(task, safe='')}/runs/{wrong_run}/events",
        f"/tasks/{quote(task, safe='')}/header",
        f"/tasks/{quote(task, safe='')}/header",
    ]
    for path in [None, *paths]:
        if path is not None:
            response = request(
                "GET",
                join_url(config.zebra_base_url, path),
                headers={"Authorization": f"Bearer {grant}"},
                timeout=2,
            )
            statuses.append(response.status)
        with db.connect_task_io() as c:
            c.execute("SET TRANSACTION READ ONLY")
            row = c.execute(
                "SELECT EXISTS(SELECT 1 FROM host_grant_replay_ledger "
                "WHERE deployment_namespace=%s AND issuer=%s AND jti=%s)::int AS n",
                (namespace, claims["iss"], claims["jti"]),
            ).fetchone()
            if row is None:
                raise E2EError("authority_replay_index_missing")
            counts.append(row["n"])
    return {
        "http_statuses": statuses,
        "replay_counts": counts,
        "target_run_changed": wrong_run != run,
        "same_grant_reused": True,
    }


def source_status(config: Config, source: str) -> str:
    from agent_storage.postgres.database import PostgresDatabase
    from psycopg.conninfo import conninfo_to_dict

    namespace = json.loads(Path(config.isolation_manifest).read_text())["namespace_id"]
    if (
        not re.fullmatch(r"[a-f0-9]{16}000000000000000[01]", source)
        or conninfo_to_dict(config.trench_database_dsn).get("dbname") != namespace + "_trench"
    ):
        raise E2EError("authority_owned_scratch_source_required")
    with PostgresDatabase(
        config.trench_database_dsn, deployment_namespace=namespace
    ).connect_task_io() as c:
        c.execute("SET TRANSACTION READ ONLY")
        row = c.execute(
            "SELECT status FROM trench_ai_user_subscriptions WHERE subscription_id=%s "
            "AND source_id=%s AND user_id=%s AND workspace_id=%s",
            ("qa-sub-" + source, source, config.user_id, config.workspace_id),
        ).fetchone()
    if row is None:
        raise E2EError("authority_owned_scratch_source_missing")
    return str(row["status"])


def operate_authority(
    config: Config,
    *,
    subcase: str,
    conversation_key: str,
    run_id: str,
    turn_id: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    if subcase not in SUBCASES:
        raise E2EError("authority_subcase_unimplemented")
    joint_preflight(config)
    task, thread = task_binding(config, conversation_key=conversation_key, simple_slice=True)
    turn_response = request(
        "GET",
        join_url(config.bff_url, f"/api/trench-ai/turns/{quote(turn_id, safe='')}"),
        headers=cookie_headers(config),
        timeout=2,
    )
    require_status(turn_response, {200})
    data = json_object(turn_response).get("data")
    if not isinstance(data, dict) or not isinstance(data.get("turn"), dict):
        raise E2EError("authority_turn_binding_missing")
    turn = data["turn"]
    if turn.get("run_id") != run_id or turn.get("conversation_key") != conversation_key:
        raise E2EError("authority_turn_run_binding_mismatch")
    deadline = time.monotonic() + config.timeout_seconds
    op: dict[str, Any] = {
        "schema_version": SCHEMA,
        "scope": "actual_scratch_authority_http_and_native_pg",
        "provider_or_receipt_injection": False,
        "task_id": task,
        "run_id": run_id,
        "subcase": subcase,
    }
    if subcase == "scope_denial":
        op.update(scope_denial(config, task, thread, run_id), action_accepted=True)
    elif subcase == "unknown_write_receipt":
        op["source_id"] = source_id
        op["source_before"] = source_status(config, source_id or "")
        op["action_accepted"] = True  # Only observes the actual Harness call, no injected write.
    cleanup_deadline: float | None = None
    while time.monotonic() < deadline:
        native = native_authority(config, task, run_id, min(deadline, cleanup_deadline or deadline))
        if op.get("action_accepted") and native["status"] in {
            "cancelled",
            "failed",
            "completed",
            "awaiting_turn",
        }:
            cleanup_deadline = cleanup_deadline or time.monotonic() + 5
        if cleanup_deadline and time.monotonic() >= cleanup_deadline:
            raise E2EError("authority_terminal_cleanup_deadline")
        rows = native["rows"]
        if subcase == "cancel" and not op.get("action_accepted"):
            model = [
                r
                for r in rows
                if r["event_type"] in {"model_request_started", "model_response_received"}
                and r.get("stage") != "public_expression"
                and r.get("purpose") != "public_expression"
            ]
            worker = native["worker"]
            if (
                not model
                or model[-1]["event_type"] != "model_request_started"
                or worker.get("coverage_complete") is not True
                or worker.get("execution_threads") != 1
                or worker.get("model_threads", 0) < 1
            ):
                time.sleep(0.05)
                continue
            op.update(worker_before=worker, armed_sequence=rows[-1]["task_sequence"])
            response = request(
                "POST",
                join_url(config.bff_url, f"/api/trench-ai/turns/{quote(turn_id, safe='')}/cancel"),
                headers=cookie_headers(config),
                timeout=2,
            )
            require_status(response, {200})
            op["action_accepted"] = True
        elif subcase == "approval" and not op.get("action_accepted"):
            pending = [r for r in rows if r["event_type"] == "approval_requested"]
            if len(pending) != 1 or native["status"] != "waiting_approval":
                raise E2EError("authority_browser_must_observe_real_approval_before_operator")
            target = pending[0]
            if not re.fullmatch(r"[a-f0-9]{64}", target.get("fingerprint") or ""):
                raise E2EError("authority_approval_fingerprint_missing")
            grant = obtain_grant(config, thread, run_id)
            response = request(
                "POST",
                join_url(config.zebra_base_url, f"/approvals/{native['segment']}/reject"),
                headers={"Authorization": f"Bearer {grant}", "Content-Type": "application/json"},
                payload={"operator": config.user_id, "reason": "Isolated QA rejects execution"},
                timeout=2,
            )
            require_status(response, {200})
            op.update(target_call_id=target["call"], decision="reject", action_accepted=True)
        if (
            op.get("action_accepted")
            and native["lease"].get("released") is True
            and all(
                type(native["worker"].get(k)) is int and native["worker"][k] == 0 for k in COUNTERS
            )
            and native["status"] in {"cancelled", "failed", "completed", "awaiting_turn"}
        ):
            if subcase == "unknown_write_receipt":
                writes = [
                    r
                    for r in rows
                    if r["event_type"] == "tool_execution_started"
                    and r.get("tool_name") == "sources.pause"
                ]
                if len(writes) != 1:
                    raise E2EError("authority_single_native_write_required")
                op.update(
                    target_call_id=writes[0]["call"],
                    source_after=source_status(config, source_id or ""),
                )
            if task_binding(config, conversation_key=conversation_key, simple_slice=True) != (
                task,
                thread,
            ):
                raise E2EError("authority_task_binding_changed")
            return {**op, "native": native}
        time.sleep(0.05)
    raise E2EError("authority_actual_terminal_not_observed")


def main() -> int:
    from run_acceptance import REQUIRED_ENV
    from support import load_config

    try:
        if os.environ.get("ZEBRA_E2E_P1_FROZEN") != "1":
            raise E2EError("authority_latest_build_freeze_required")
        raw = sys.stdin.read(8193)
        if len(raw.encode()) > 8192:
            raise E2EError("authority_operator_input_limit")
        inputs = json.loads(raw)
        if set(inputs) - {
            "case_id",
            "subcase",
            "conversation_key",
            "run_id",
            "turn_id",
            "source_id",
        }:
            raise E2EError("authority_operator_input_invalid")
        if inputs.pop("case_id") != "authority":
            raise E2EError("authority_operator_input_invalid")
        result = operate_authority(load_config(os.environ, REQUIRED_ENV), **inputs)
        print(json.dumps({"status": "passed", **result}))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": exc.code
                    if isinstance(exc, E2EError)
                    else "authority_actual_evidence_unproven",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
