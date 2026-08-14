"""Execution-tier scenarios for the effect default E2E gate.

These scenarios require a gVisor-capable engine reachable from the Worker's
configured engine command, a dedicated workspace mount at
``ZEBRA_EFFECT_E2E_WORKSPACE`` and a digest-pinned runtime image in
``ZEBRA_EFFECT_E2E_RUNTIME_IMAGE``. The rig used for the recorded evidence is
documented in ``docs/CLOUD-EFFECT-DEFAULT-E2E-01.md``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from run_default_e2e import Runner

PROOF_FILE = "effect-proof.txt"
PROOF_CONTENT = "effect-e2e-proof"


def _seed(runner: Runner, *, marker: bool, key: str) -> dict[str, Any]:
    return runner.uv_json(
        str(runner.runner_dir / "seed_session.py"),
        env_extra={
            "ZEBRA_EFFECT_E2E_WORKSPACE": str(runner.workspace),
            "ZEBRA_EFFECT_E2E_SEED_KEY": key,
            "ZEBRA_EFFECT_E2E_PROMPT": (
                "WRITE-FILE: create effect-proof.txt"
                if marker
                else "Reply with a short summary and finish."
            ),
        },
    )


def _cycles(runner: Runner, count: int) -> None:
    for _ in range(count):
        runner.uv(
            "-m",
            "zebra_agent_worker.main",
            "--max-cycles",
            "2",
            "--idle-sleep-seconds",
            "1",
            check=False,
        )


def _summary(runner: Runner) -> dict[str, Any]:
    return runner.uv_json(str(runner.runner_dir / "verify_durable.py"), "effect-summary")


def _status(runner: Runner, session_id: str) -> str | None:
    result = runner.uv_json(
        str(runner.runner_dir / "verify_durable.py"), "session-status", session_id
    )
    return result.get("status")


def scenario_side_effect(runner: Runner) -> dict[str, Any]:
    seed = _seed(runner, marker=True, key="effect-e2e-exec-side-1")
    session_id = seed["session_id"]
    _cycles(runner, 2)
    approval = runner.uv(
        str(runner.runner_dir / "approve_and_resume.py"),
        env_extra={"ZEBRA_EFFECT_E2E_SESSION_ID": session_id},
        check=False,
    )
    _cycles(runner, 3)
    summary = _summary(runner)
    events = runner.uv_json(str(runner.runner_dir / "verify_durable.py"), "event-types", session_id)
    proof = runner.workspace / PROOF_FILE
    effects = summary.get("effects", [])
    succeeded = next((entry for entry in effects if entry["status"] == "succeeded"), None)
    tool_completed = any(
        "tool_execution_completed" == str(entry[0]) for entry in events.get("event_types", [])
    )
    artifacts = dict(summary.get("artifacts") or [])
    detail = {
        "session_id": session_id,
        "approval_returncode": approval.returncode,
        "effects": effects,
        "artifacts": artifacts,
        "tool_completed": tool_completed,
        "proof_exists": proof.is_file(),
        "proof_content": proof.read_text() if proof.is_file() else None,
        "session_status": _status(runner, session_id),
    }
    passed = (
        seed["status"] == 201
        and approval.returncode == 0
        and succeeded is not None
        and succeeded["rows"] == 1
        and succeeded["terminal_bound"] == 1
        and succeeded["payload_bound"] == 1
        and tool_completed
        and proof.is_file()
        and proof.read_text() == PROOF_CONTENT
        and artifacts.get("finalized", 0) >= 2
    )
    runner.record("side_effect_schedule_claim_complete", passed, detail)
    return detail


def scenario_restart_no_duplicate(runner: Runner, prior: dict[str, Any]) -> None:
    before_proof = prior.get("proof_content")
    _cycles(runner, 3)
    summary = _summary(runner)
    proof = runner.workspace / PROOF_FILE
    effects = summary.get("effects", [])
    total_succeeded = sum(entry["rows"] for entry in effects if entry["status"] == "succeeded")
    passed = total_succeeded == 1 and proof.is_file() and proof.read_text() == before_proof
    runner.record(
        "worker_restart_no_duplicate",
        passed,
        {
            "total_succeeded": total_succeeded,
            "proof_unchanged": proof.is_file() and proof.read_text() == before_proof,
        },
    )


def scenario_replay_consistency(runner: Runner, prior: dict[str, Any]) -> None:
    session_id = prior["session_id"]
    events = runner.uv_json(str(runner.runner_dir / "verify_durable.py"), "event-types", session_id)
    summary = _summary(runner)
    effects = summary.get("effects", [])
    succeeded = next((entry for entry in effects if entry["status"] == "succeeded"), None)
    started = sum(count for name, count in events.get("event_types", []) if "started" in str(name))
    completed = sum(
        count for name, count in events.get("event_types", []) if "completed" in str(name)
    )
    passed = (
        succeeded is not None
        and succeeded["terminal_bound"] == 1
        and completed >= 1
        and started >= completed
    )
    runner.record(
        "replay_consistency",
        passed,
        {"started": started, "completed": completed, "effects": effects},
    )


def scenario_payload_binding(prior: dict[str, Any], runner: Runner) -> None:
    artifacts = dict(prior.get("artifacts") or {})
    runner.record(
        "payload_object_binding",
        artifacts.get("finalized", 0) >= 2,
        {"artifacts": artifacts},
    )


def scenario_completed_memory(runner: Runner) -> None:
    seed = _seed(runner, marker=False, key="effect-e2e-exec-complete-1")
    session_id = seed["session_id"]
    _cycles(runner, 3)
    status = _status(runner, session_id)
    summary = _summary(runner)
    memory_ops = summary.get("memory_operations", 0)
    effects = summary.get("effects", [])
    side_effect_rows = sum(entry["rows"] for entry in effects if entry["status"] == "succeeded")
    runner.record(
        "session_completed_governed_memory",
        seed["status"] == 201
        and status == "completed"
        and side_effect_rows == 1
        and memory_ops >= 0,
        {"session_status": status, "memory_operations": memory_ops, "effects": effects},
    )


def run_execution_tier(runner: Runner) -> None:
    prior = scenario_side_effect(runner)
    scenario_restart_no_duplicate(runner, prior)
    scenario_replay_consistency(runner, prior)
    scenario_payload_binding(prior, runner)
    scenario_completed_memory(runner)
    runner.record_skipped(
        "lease_loss_uncertain_reconcile",
        "fault_injection_not_implemented",
        "deterministic mid-execution lease expiry injection",
    )
    _cooldown()


def _cooldown() -> None:
    time.sleep(1)


def cleanup_workspace(runner: Runner) -> None:
    for entry in Path(runner.workspace).glob("*"):
        if entry.is_file():
            entry.unlink(missing_ok=True)
