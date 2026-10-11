"""Real browser observation faults; fault samples never enter the healthy P95 cohort."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from isolation import joint_preflight
from joint_acceptance import native_admission_gate, native_source_identity
from joint_business_seed import validate_seed
from support import Config, E2EError, task_binding

NAVIGATION_CASES = frozenset({"frame_disconnect", "navigation"})


def navigation_prompt(case_id: str, marker: str, seed: Mapping[str, Any]) -> str:
    if case_id not in NAVIGATION_CASES:
        raise E2EError("navigation_executor_unimplemented")
    validate_seed(seed)
    return (
        f"对订阅中的 QA {seed['seed_id']} 来源做只读核验。"
        "先 events.search_history limit=20，随后分别读取两条来源独立的历史事件；"
        "再查询另一页以确认覆盖范围。12%和8%是独立来源，不得合并冲突结论。"
        "不要修改数据、订阅或重复工具动作。浏览器可能离线或切换页面，"
        f"后台仍完成同一个请求。最终最后一段只放 {marker}。"
    )


def validate_navigation(evidence: Mapping[str, Any]) -> None:
    """Fault recovery has replay clocks: deliberately NOT validate_live_evidence/P95."""
    fault = evidence.get("navigation", {})
    frames = evidence.get("frames", [])
    if (
        evidence.get("case_id") not in NAVIGATION_CASES
        or evidence.get("scope") != "real_scratch_host_browser_sse"
        or evidence.get("fixture_routes") is not False
        or evidence.get("post_count") != 1
        or evidence.get("final_count") != 1
        or evidence.get("admission_terminal") is not False
        or fault.get("scope") != "actual_browser_observation_faults"
        or fault.get("fixture_provider") is not False
        or fault.get("fault_cohort") is not True
        or fault.get("healthy_samples") != 0
        or fault.get("observe_only") is not True
        or not isinstance(frames, list)
        or not 1 <= len(frames) <= 256
        or evidence.get("cleanup", {}).get("worker_cleanup", {}).get("status") != "passed"
    ):
        raise E2EError("navigation_real_fault_contract")
    if any(type(f.get("cursor")) is not int or f["cursor"] < 1 for f in frames):
        raise E2EError("navigation_unpositioned_frame")
    if evidence["case_id"] == "frame_disconnect":
        replay = fault.get("frame_disconnect", {})
        baseline, cuts, restored = (replay.get(k, []) for k in ("baseline", "cuts", "restored"))
        cursors = [f["cursor"] for f in baseline]
        if (
            not baseline
            or len(baseline) > 256
            or cursors != sorted(set(cursors))
            or replay.get("ui_transport_failed") is not True
            or replay.get("ui_reconnected") is not True
            or replay.get("real_eof") is not True
            or replay.get("no_duplicate_tools") is not True
            or replay.get("scope") != "native_browser_per_frame_cancel_replay_and_live_ui_fault"
            or len(cuts) != len(baseline)
            or restored != baseline
            or [c.get("cut_cursor") for c in cuts] != cursors
            or any(
                c.get("request_started") is not True
                or c.get("abort_called") is not True
                or c.get("reader_cancelled") is not True
                for c in cuts
            )
            or any(
                c.get("next_cursor") != (cursors[i + 1] if i + 1 < len(cursors) else None)
                for i, c in enumerate(cuts)
            )
        ):
            raise E2EError("per_frame_disconnect_replay_unproven")
    else:
        state = fault.get("navigation", {})
        if (
            not all(
                state.get(k) is True
                for k in (
                    "refresh",
                    "a_b_a",
                    "late_ack",
                    "b_not_contaminated",
                    "same_admission",
                    "no_duplicate_dom_tools",
                    "response_unmodified",
                    "spa_navigation",
                )
            )
            or type(state.get("dom_tool_count")) is not int
            or state["dom_tool_count"] < 1
            or not state.get("a_key")
            or state.get("a_key") == state.get("b_key")
        ):
            raise E2EError("navigation_epoch_or_observe_only_unproven")


def native_navigation(config: Config, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Indexed canonical Run proof; scalar <=256 rows, no whole-history bodies."""
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_replay_headers import read_run_header

    task, thread = task_binding(
        config, conversation_key=evidence["conversation_key"], simple_slice=True
    )
    scope = joint_preflight(config)["namespace_id"]
    if not isinstance(scope, str):
        raise E2EError("navigation_namespace_unproven")
    db = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    with db.connect_task_io(deadline=time.monotonic() + 2) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        header = read_run_header(connection, scope, TaskId(UUID(task)), evidence["run_id"], None)
        if header.anchor is None or header.control_only:
            raise E2EError("navigation_run_not_canonical")
        rows = connection.execute(
            "SELECT task_sequence,event_id,event_type,payload->>'tool_call_id' AS tool_call_id,"
            "payload->>'model_call_id' AS model_call_id,payload->>'provider' AS provider,"
            "payload->>'request_hash' AS request_hash,payload->>'normalized_error' AS model_error "
            "FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
            "AND task_sequence BETWEEN %s AND %s ORDER BY task_sequence LIMIT 257",
            (scope, task, header.start, header.stop - 1 if header.stop else header.highwater),
        ).fetchall()
    return validate_native_navigation_rows(
        rows, task=task, thread=thread, run_id=evidence["run_id"]
    )


def validate_native_navigation_rows(
    rows: list[dict[str, Any]], *, task: str, thread: str, run_id: str
) -> dict[str, Any]:
    if len(rows) > 256:
        raise E2EError("navigation_native_proof_limit")
    starts = [r for r in rows if r["event_type"] == "tool_execution_started"]
    completions = [r for r in rows if r["event_type"] == "tool_execution_completed"]
    models = [r for r in rows if r["event_type"] == "model_response_received"]
    identities = [r["tool_call_id"] for r in starts]
    if (
        not starts
        or not models
        or len(identities) != len(set(identities))
        or any(not isinstance(identity, str) or not identity for identity in identities)
        or [r["event_type"] for r in rows].count("answer_committed") != 1
        or [r["event_type"] for r in rows].count("session_command_accepted") != 1
        or any(
            r.get("provider") not in {"deepseek", "openai", "openai-compatible"}
            or not r.get("model_call_id")
            or not r.get("request_hash")
            or r.get("model_error")
            for r in models
        )
        or any(not isinstance(r.get("tool_call_id"), str) for r in completions)
        or sorted(r["tool_call_id"] for r in completions) != sorted(identities)
    ):
        raise E2EError("navigation_real_run_or_duplicate_tools")
    return {
        "task_id": task,
        "host_thread": thread,
        "run_id": run_id,
        "scope": "canonical_run_scalar_headers",
        "model_count": len(models),
        "attempt_count": sum(r["event_type"] == "harness_attempt_started" for r in rows),
        "source_headers_sha256": sha256(
            json.dumps(
                [(str(r.get("event_id")), r.get("task_sequence"), r["event_type"]) for r in rows]
            ).encode()
        ).hexdigest(),
        "tool_ids": identities,
        "tool_count": len(starts),
        "final_count": 1,
        "whole_history_hydrated": False,
        "fixture_provider": False,
    }


def run_navigation_case(
    config: Config,
    environment: Mapping[str, str],
    evidence_dir: Path,
    *,
    case_id: str,
    seed: Mapping[str, Any],
) -> dict[str, Any]:
    """Runs the real shared browser entrypoint only on the latest Python freeze."""
    joint_preflight(config)
    native_admission_gate(config)
    identity = native_source_identity(config)
    if not identity or any(
        not isinstance(p, dict) or p.get("current_checkout_match") is not True
        for p in identity.values()
    ):
        raise E2EError("navigation_latest_freeze_not_deployed")
    marker = "ZEBRA_QA_SIMPLE_" + uuid4().hex
    evidence_dir.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve().parents[3].parent / (
        "Trench/toc-frontend/scripts/strategy-joint-acceptance.mjs"
    )
    inputs = {
        "case_id": case_id,
        "prompt": navigation_prompt(case_id, marker, seed),
        "base_url": config.bff_url,
        "cookie": config.session_cookie,
        "expected": marker,
        "timeout_ms": config.timeout_seconds * 1000,
        "python": sys.executable,
        "guard_script": str(Path(__file__).with_name("run_acceptance.py")),
        "cleanup_script": str(Path(__file__).with_name("terminal_probe.py")),
        "evidence_dir": str(evidence_dir.resolve()),
        "tls_spki": environment.get("ZEBRA_E2E_TLS_SPKI", ""),
    }
    result = subprocess.run(
        [environment.get("ZEBRA_E2E_NODE", "node"), str(script)],
        cwd=script.parent.parent,
        env=dict(environment),
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
        timeout=config.timeout_seconds + 120,
        check=False,
    )
    if result.returncode != 0:
        raise E2EError("navigation_browser_fault_executor_failed")
    path = evidence_dir / (case_id.replace("_", "-") + ".json")
    if path.stat().st_size > 1_048_576:
        raise E2EError("navigation_browser_evidence_limit")
    evidence = json.loads(path.read_text())
    validate_navigation(evidence)
    # Compare pre/post probe canonical ledgers: observer GETs cannot restart harness/tools.
    after = native_navigation(config, evidence)
    if after != evidence["navigation"].get("native_before"):
        raise E2EError("navigation_observation_mutated_canonical_run")
    return {
        "case_id": case_id,
        "status": "fault_slice_passed",
        "source_identity": identity,
        "native": after,
        "browser": evidence,
        "full_goal_passed": False,
        "healthy_samples": 0,
        "fault_samples": 1,
    }


if __name__ == "__main__":
    import argparse
    import os

    from joint_business_seed import seed_business
    from run_acceptance import REQUIRED_ENV
    from support import load_config

    parser = argparse.ArgumentParser(
        description="Real navigation faults, never healthy P95 samples"
    )
    parser.add_argument("--case", choices=sorted(NAVIGATION_CASES))
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--native-check", action="store_true")
    arguments = parser.parse_args()
    try:
        config = load_config(os.environ, REQUIRED_ENV)
        if arguments.native_check:
            raw = sys.stdin.read(8193)
            if len(raw) > 8192:
                raise E2EError("navigation_identity_input_limit")
            data = json.loads(raw)
            print(json.dumps(native_navigation(config, data)))
            raise SystemExit(0)
        if not arguments.case or arguments.evidence_dir is None:
            parser.error("--case and --evidence-dir are required for a browser run")
        report = run_navigation_case(
            config,
            os.environ,
            arguments.evidence_dir,
            case_id=arguments.case,
            seed=seed_business(config),
        )
        (arguments.evidence_dir / "navigation-result.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
    except (E2EError, ValueError, OSError, subprocess.SubprocessError):
        print("ZEBRA_JOINT_NAVIGATION=BLOCKED healthy_samples=0")
        raise SystemExit(2) from None
    print("ZEBRA_JOINT_NAVIGATION=FAULT_SLICE_PASSED healthy_samples=0 full_goal_passed=false")
