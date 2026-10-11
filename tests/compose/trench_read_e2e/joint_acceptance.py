"""One real joint slice. Other thirteen cases and healthy P95 remain open."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from isolation import joint_preflight
from support import Config, ConfigError, E2EError, load_config, origin, task_binding


def validate_simple_answer(evidence: Mapping[str, Any], expected: str) -> None:
    if (
        evidence.get("scope") != "real_scratch_host_browser_sse"
        or evidence.get("fixture_routes") is not False
        or evidence.get("post_count") != 1
        or evidence.get("final_count") != 1
        or evidence.get("final_sha256") != sha256(expected.encode()).hexdigest()
        or evidence.get("admission_terminal") is not False
        or evidence.get("stream_open_before_terminal") is not True
        or evidence.get("public_output_count") != 0
        or evidence.get("tool_count") != 0
    ):
        raise ValueError("simple_answer_contract")
    validate_live_evidence(evidence)


def validate_live_evidence(evidence: Mapping[str, Any]) -> None:
    """Common real-live evidence; no classification based on final answer prose."""
    if (
        evidence.get("scope") != "real_scratch_host_browser_sse"
        or evidence.get("fixture_routes") is not False
        or evidence.get("post_count") != 1
        or evidence.get("final_count") != 1
        or evidence.get("admission_terminal") is not False
        or evidence.get("stream_open_before_terminal") is not True
    ):
        raise ValueError("joint_live_contract")
    frames = evidence.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= 256:
        raise ValueError("simple_answer_frames")
    cursors = [frame.get("cursor") for frame in frames]
    if any(type(cursor) is not int or cursor < 1 for cursor in cursors) or cursors != sorted(
        set(cursors)
    ):
        raise ValueError("simple_answer_cursors")
    timing = evidence.get("timing", {})
    if (
        timing.get("schemaVersion") != "trench.strategy-timing.v1"
        or timing.get("clock") != "document.performance.now"
        or len(timing.get("turns", [])) > 128
        or len(timing.get("events", [])) > 256
    ):
        raise ValueError("simple_answer_timing")
    turn_id = evidence.get("turn_id")
    turn: dict[str, Any] = next(
        (item for item in timing.get("turns", []) if item.get("turnId") == turn_id), {}
    )
    if turn.get("replay") is not False or not all(
        isinstance(turn.get(key), float | int)
        for key in (
            "submitAtMs",
            "admissionReceivedAtMs",
            "firstPublicTextReceiptAtMs",
            "finalCommitReceiptAtMs",
            "submitToAdmissionFeedbackMs",
        )
    ):
        raise ValueError("simple_answer_live_timing")
    if turn["firstPublicTextReceiptAtMs"] >= turn["finalCommitReceiptAtMs"]:
        raise ValueError("simple_answer_not_progressive")
    if not any(
        item.get("turnId") == turn_id
        and item.get("replay") is False
        and item.get("backgrounded") is False
        and item.get("coalesced") is False
        and isinstance(item.get("relayToPaintReadyMs"), float | int)
        for item in timing.get("events", [])
    ):
        raise ValueError("simple_answer_paint_unmeasured")
    cleanup = evidence.get("cleanup", {})
    if (
        cleanup.get("worker_cleanup", {}).get("status") != "passed"
        or not isinstance(cleanup.get("answer_observed_to_cleanup_ms"), int | float)
        or not 0 <= cleanup["answer_observed_to_cleanup_ms"] <= 5000
    ):
        raise ValueError("joint_worker_cleanup_unproven")


def native_admission_gate(config: Config) -> None:
    """Read an indexed registry prerequisite, never register/renew it on GET."""
    from agent_storage.postgres.database import PostgresDatabase

    scope = cast(str, joint_preflight(config)["namespace_id"])
    database = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    try:
        with database.connect_task_io(deadline=time.monotonic() + 2) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            row = connection.execute(
                "SELECT issuer,audience,allowed_origins,active FROM host_authority_registries "
                "WHERE deployment_namespace=%s AND host_app_id='trench' AND namespace_id=%s",
                (scope, scope),
            ).fetchone()
            if (
                row is None
                or row["issuer"] != origin(config.grant_exchange_url)
                or row["audience"] != "zebra"
                or row["active"] is not True
                or row["allowed_origins"] != [origin(config.bff_url)]
            ):
                raise E2EError("scratch_host_registration_not_ready")
    except E2EError:
        raise
    except Exception:
        raise E2EError("scratch_host_registration_not_ready") from None


def native_p0_catalog(config: Config) -> list[dict[str, object]]:
    """Three primary-key catalog reads; proof only, never schema repair on observation."""
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.migrations import MIGRATIONS

    scope = cast(str, joint_preflight(config)["namespace_id"])
    database = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    with database.connect_task_io(deadline=time.monotonic() + 2) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        rows = connection.execute(
            "SELECT version,name,checksum FROM zebra_schema_migrations "
            "WHERE version IN (72,73,74) ORDER BY version LIMIT 3"
        ).fetchall()
    expected = [
        {"version": m.version, "name": m.name, "checksum": m.checksum}
        for m in MIGRATIONS
        if m.version in (72, 73, 74)
    ]
    if len(expected) != 3 or rows != expected:
        raise E2EError("scratch_p0_migrations_not_current")
    return cast(list[dict[str, object]], rows)


def native_source_identity(config: Config) -> dict[str, object]:
    """Hash all deployed Python src bytes, not merely the progressive-output module."""
    from scratch_topology import ZEBRA, docker

    code = (
        "import hashlib,json;from pathlib import Path;root=Path('/app');"
        "files=sorted(p for group in ('apps','packages') "
        "for member in (root/group).iterdir() if (member/'src').is_dir() "
        "for p in (member/'src').rglob('*.py'));"
        "items=[(str(p.relative_to(root)),hashlib.sha256(p.read_bytes()).hexdigest()) "
        "for p in files];print(json.dumps(items))"
    )
    manifest = json.loads(Path(config.isolation_manifest).read_text())
    expected = sorted(
        (str(p.relative_to(ZEBRA)), sha256(p.read_bytes()).hexdigest())
        for group in ("apps", "packages")
        for member in (ZEBRA / group).iterdir()
        if (member / "src").is_dir()
        for p in (member / "src").rglob("*.py")
    )
    result: dict[str, object] = {}
    for role in ("worker", "zebra_api", "broker"):
        spec = manifest["containers"][role]
        actual = json.loads(docker(["exec", spec["id"], "python", "-c", code]))
        normalized = sorted(tuple(item) for item in actual)
        installed, current = dict(normalized), dict(expected)
        differences = sorted(
            name
            for name in installed.keys() | current.keys()
            if installed.get(name) != current.get(name)
        )
        result[role] = {
            "image_id": spec["image_id"],
            "source_files": len(normalized),
            "python_src_sha256": sha256(json.dumps(normalized).encode()).hexdigest(),
            "current_checkout_match": not differences,
            "mismatched_paths": differences,
        }
    return result


def native_simple_answer(config: Config, evidence: Mapping[str, Any]) -> dict[str, object]:
    """Cross-check browser identity and <=256 scalar Event headers, no body hydration."""
    from agent_storage.postgres.database import PostgresDatabase

    task, thread = task_binding(
        config, conversation_key=evidence["conversation_key"], simple_slice=True
    )
    if task == thread:
        raise E2EError("task_host_identity_alias")
    scope = cast(str, joint_preflight(config)["namespace_id"])
    database = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    try:
        with database.connect_task_io(deadline=time.monotonic() + 2) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            row = connection.execute(
                "SELECT snapshot_json->'host_capability'->'host_context' AS context "
                "FROM task_binding_snapshots WHERE deployment_namespace=%s AND task_id=%s",
                (scope, task),
            ).fetchone()
            context = row["context"] if row else {}
            refs = context.get("resource_refs", [])
            identities = {
                (ref.get("resource_type", ref.get("type")), ref.get("resource_id", ref.get("id")))
                for ref in refs
            }
            if (
                context.get("namespace_id") != scope
                or context.get("workspace_ref") != config.workspace_id
                or ("thread", thread) not in identities
                or ("principal", config.user_id) not in identities
                or ("run", evidence["run_id"]) not in identities
            ):
                raise E2EError("scratch_native_authority_mismatch")
            rows = connection.execute(
                "SELECT task_sequence,event_type,event_id FROM session_events "
                "WHERE deployment_namespace=%s AND task_id=%s ORDER BY task_sequence LIMIT 257",
                (scope, task),
            ).fetchall()
            kinds = [row["event_type"] for row in rows]
            if (
                len(rows) > 256
                or kinds.count("answer_committed") != 1
                or kinds.count("model_response_received") < 1
                or any(kind in {"public_output", "tool_execution_started"} for kind in kinds)
            ):
                raise E2EError("scratch_native_simple_answer_mismatch")
            request = next(row for row in rows if row["event_type"] == "model_request_started")
            policy = connection.execute(
                "SELECT payload->'public_output_policy' AS policy FROM session_events "
                "WHERE deployment_namespace=%s AND event_id=%s",
                (scope, request["event_id"]),
            ).fetchone()
            head = connection.execute(
                "SELECT through_sequence,state_bytes,"
                "state_json::jsonb->>'policy_json' AS policy_json, "
                "state_json::jsonb->>'published_count' AS published_count "
                "FROM worker_progress_heads WHERE deployment_namespace=%s AND task_id=%s "
                "AND run_id=%s LIMIT 2",
                (scope, task, evidence["run_id"]),
            ).fetchall()
            if (
                not policy
                or not policy["policy"]
                or len(head) != 1
                or json.loads(head[0]["policy_json"]) != policy["policy"]
            ):
                raise E2EError("scratch_public_policy_not_frozen")
            return {
                "task_id": task,
                "host_thread": thread,
                "run_id": evidence["run_id"],
                "headers": [dict(row, event_id=str(row["event_id"])) for row in rows],
                "body_hydration": False,
                "final_commits": 1,
                "frozen_public_output_policy": policy["policy"],
                "worker_progress_head": head,
            }
    except E2EError:
        raise
    except Exception:
        raise E2EError("scratch_native_evidence_unavailable") from None


def run_joint(
    environment: Mapping[str, str],
    evidence_dir: Path,
    *,
    preflight_only: bool = False,
    guard: bool = False,
    case_id: str = "simple_answer",
    business_seed: Mapping[str, Any] | None = None,
) -> int:
    from run_acceptance import MANIFEST, REQUIRED_ENV

    contract = json.loads(MANIFEST.read_text())["joint_acceptance"]
    result: dict[str, object] = {
        "schema_version": "zebra.joint-slice.v1",
        "scope": case_id + "_slice_only",
        "status": "blocked",
        "full_goal_passed": False,
        "healthy_samples": 0,
        "required_healthy_samples": 100,
        "remaining_cases": [item["id"] for item in contract["cases"]],
    }
    try:
        if case_id not in {"simple_answer", "multi_source", "tool_only"}:
            raise E2EError("joint_case_executor_not_implemented")
        inputs = dict(environment)
        # These legacy fault/tool inputs are deliberately unused in this no-fault slice.
        for key in ("TRENCH_E2E_BUSINESS_SNAPSHOT_URL", "ZEBRA_E2E_WORKER_RESTART_URL"):
            inputs.setdefault(key, inputs.get("TRENCH_E2E_BFF_URL", ""))
        inputs.setdefault("TRENCH_E2E_EVENT_ID", "unused_in_simple_answer")
        config = load_config(inputs, REQUIRED_ENV)
        result["preflight"] = joint_preflight(config)
        native_admission_gate(config)
        result["p0_migrations"] = native_p0_catalog(config)
        if not preflight_only:
            identity = native_source_identity(config)
            result["source_identity"] = identity
            if not all(
                isinstance(identity.get(role), Mapping)
                and cast(Mapping[str, object], identity[role]).get("current_checkout_match") is True
                for role in ("worker", "zebra_api", "broker")
            ):
                raise E2EError("joint_latest_source_not_verified")
            script = Path(__file__).resolve().parents[3].parent / (
                "Trench/toc-frontend/scripts/strategy-joint-acceptance.mjs"
            )
            if not script.is_file():
                raise E2EError("joint_browser_script_unavailable")
            expected = "ZEBRA_QA_SIMPLE_" + uuid.uuid4().hex
            evidence_dir.mkdir(parents=True, exist_ok=True)
            # Secrets are stdin/environment inputs, never argv or evidence. No app env discovery.
            browser_input = {
                "case_id": case_id,
                "base_url": config.bff_url,
                "cookie": config.session_cookie,
                "expected": expected,
                "timeout_ms": config.timeout_seconds * 1000,
                "guard_script": str(Path(__file__).with_name("run_acceptance.py")),
                "cleanup_script": str(Path(__file__).with_name("terminal_probe.py")),
                "python": sys.executable,
                "evidence_dir": str(evidence_dir.resolve()),
                "tls_spki": environment.get("ZEBRA_E2E_TLS_SPKI", ""),
            }
            if case_id != "simple_answer":
                from joint_business_seed import validate_seed
                from joint_public_cases import public_prompt

                if business_seed is None:
                    raise E2EError("joint_case_business_seed_required")
                validate_seed(business_seed)
                browser_input["prompt"] = public_prompt(case_id, expected, business_seed)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as private_inputs:
                if environment.get("ZEBRA_E2E_COMMIT_VISIBILITY") == "1":
                    json.dump(inputs, private_inputs)
                    private_inputs.flush()
                    browser_input["commit_inputs_path"] = private_inputs.name
                completed = subprocess.run(
                    [environment.get("ZEBRA_E2E_NODE", "node"), str(script)],
                    cwd=script.parent.parent,
                    env=dict(environment),
                    input=json.dumps(browser_input),
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds + 60,
                    check=False,
                )
            if completed.returncode != 0:
                phase = re.search(r"REAL_SIMPLE_ANSWER=FAILED phase=([a-z_]+)", completed.stderr)
                raise E2EError("real_browser_slice_failed_" + (phase[1] if phase else "launch"))
            path = evidence_dir / (case_id.replace("_", "-") + ".json")
            if path.stat().st_size > 1_048_576:
                raise E2EError("browser_evidence_oversized")
            browser_evidence = json.loads(path.read_text())
            if case_id == "simple_answer":
                validate_simple_answer(browser_evidence, expected)
                result["native"] = native_simple_answer(config, browser_evidence)
            else:
                from joint_public_cases import native_partial, validate_partial

                validate_partial(browser_evidence)
                result["native"] = native_partial(config, browser_evidence)
            result[case_id] = "slice_passed"
            if case_id == "simple_answer":
                result[case_id] = "passed"  # Preserve the existing launcher's exact slice seam.
            result["healthy_samples"] = 1
            result["remaining_cases"] = [
                item["id"]
                for item in contract["cases"]
                if not (item["id"] == case_id and case_id in {"simple_answer", "multi_source"})
            ]
            if case_id == "tool_only":
                result["remaining_case_gate"] = "recovery_no_duplicate_milestones"
        result["status"] = "preflight_passed" if preflight_only else "slice_passed"
    except ConfigError as error:
        result["missing_environment"] = error.missing
        result["invalid_environment"] = error.invalid
    except E2EError as error:
        result["reason"] = error.code
    except (ValueError, OSError, subprocess.SubprocessError):
        result["reason"] = "bounded_joint_slice_failed"
    if guard:
        return 0 if result["status"] == "preflight_passed" else 2
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "joint-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"ZEBRA_JOINT_SLICE={str(result['status']).upper()}")
    # Even a real simple-answer pass cannot close fourteen cases or a P95 distribution.
    return 2
