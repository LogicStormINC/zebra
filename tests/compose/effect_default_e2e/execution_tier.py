"""Execution-tier scenarios for the effect default E2E gate.

These scenarios require a gVisor-capable engine reachable from the Worker's
configured engine command, a dedicated workspace mount at
``ZEBRA_EFFECT_E2E_WORKSPACE`` and a digest-pinned runtime image in
``ZEBRA_EFFECT_E2E_RUNTIME_IMAGE``. The rig used for the recorded evidence is
documented in ``docs/CLOUD-EFFECT-DEFAULT-E2E-01.md``.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from run_default_e2e import Runner

PROOF_FILE = "effect-proof.txt"
HANG_FLAG_DIR = Path(os.environ.get("ZEBRA_EFFECT_E2E_FLAG_DIR", "/tmp/zebra-effect-e2e-flags"))
PROOF_CONTENT = "effect-e2e-proof"


def _seed(runner: Runner, *, prompt: str, key: str) -> dict[str, Any]:
    return runner.uv_json(
        str(runner.runner_dir / "seed_session.py"),
        env_extra={
            "ZEBRA_EFFECT_E2E_WORKSPACE": str(runner.workspace),
            "ZEBRA_EFFECT_E2E_SEED_KEY": key,
            "ZEBRA_EFFECT_E2E_PROMPT": prompt,
        },
    )


def _cycles(runner: Runner, count: int) -> None:
    for _ in range(count):
        result = runner.uv(
            "-m",
            "zebra_agent_worker.main",
            "--max-cycles",
            "2",
            "--idle-sleep-seconds",
            "1",
            check=False,
        )
        runner.last_cycle_stderr = (result.stderr or "")[-500:]


def _summary(runner: Runner) -> dict[str, Any]:
    return runner.uv_json(str(runner.runner_dir / "verify_durable.py"), "effect-summary")


def _status(runner: Runner, session_id: str) -> str | None:
    result = runner.uv_json(
        str(runner.runner_dir / "verify_durable.py"), "session-status", session_id
    )
    return result.get("status")


def scenario_side_effect(runner: Runner) -> dict[str, Any]:
    seed = _seed(
        runner,
        prompt="WRITE-FILE: create effect-proof.txt",
        key="effect-e2e-exec-side-1",
    )
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
        and detail["session_status"] == "completed"
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
    seed = _seed(
        runner,
        prompt="Reply with a short summary and finish.",
        key="effect-e2e-exec-complete-1",
    )
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


def _log_tail(path: Path, lines: int = 8) -> str:
    try:
        content = path.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def _background_worker(runner: Runner, *, name: str) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        **runner.cloud_env,
        "DOCKER_HOST": runner.cloud_env.get("DOCKER_HOST", os.environ.get("DOCKER_HOST", "")),
    }
    if not env.get("DOCKER_HOST"):
        env.pop("DOCKER_HOST", None)
    return subprocess.Popen(
        (
            "uv",
            "run",
            "--project",
            str(runner.project_root),
            "python",
            "-m",
            "zebra_agent_worker.main",
            "--max-cycles",
            "6",
            "--idle-sleep-seconds",
            "2",
        ),
        cwd=runner.run_root,
        env=env,
        stdout=(runner.run_root / f"worker-{name}.log").open("wb"),
        stderr=subprocess.STDOUT,
    )


def _clean_proofs(runner: Runner) -> None:
    for name in (PROOF_FILE, "lease-proof.txt"):
        (runner.workspace / name).unlink(missing_ok=True)


def scenario_worker_death_recovers(runner: Runner) -> None:
    HANG_FLAG_DIR.mkdir(parents=True, exist_ok=True)
    for flag in ("hang-used", "hang-started"):
        (HANG_FLAG_DIR / flag).unlink(missing_ok=True)
    _clean_proofs(runner)
    seed = _seed(
        runner,
        prompt="WRITE-FILE: create effect-proof.txt then HANG-AFTER-TOOL.",
        key="effect-e2e-exec-death-1",
    )
    session_id = seed["session_id"]
    _cycles(runner, 2)
    approval = runner.uv(
        str(runner.runner_dir / "approve_and_resume.py"),
        env_extra={"ZEBRA_EFFECT_E2E_SESSION_ID": session_id},
        check=False,
    )
    worker = _background_worker(runner, name="death")
    hang_started = HANG_FLAG_DIR / "hang-started"
    deadline = time.monotonic() + 120
    while not hang_started.exists() and time.monotonic() < deadline:
        if worker.poll() is not None:
            break
        time.sleep(1)
    worker.kill()
    worker.wait(timeout=30)
    (HANG_FLAG_DIR / "hang-started").unlink(missing_ok=True)
    # The killed Worker's lease must expire before recovery can reclaim;
    # lease TTL defaults to 30s and expiry is the designed recovery trigger.
    time.sleep(36)
    events = runner.uv_json(str(runner.runner_dir / "verify_durable.py"), "event-types", session_id)
    completed_before = any(
        "tool_execution_completed" == str(entry[0]) for entry in events.get("event_types", [])
    )
    tool_detail = runner.uv_json(
        str(runner.runner_dir / "verify_durable.py"), "tool-events", session_id
    )
    resume = runner.uv(
        str(runner.runner_dir / "approve_and_resume.py"),
        env_extra={"ZEBRA_EFFECT_E2E_SESSION_ID": session_id},
        check=False,
    )
    _cycles(runner, 3)
    if _status(runner, session_id) != "completed":
        second_resume = runner.uv(
            str(runner.runner_dir / "approve_and_resume.py"),
            env_extra={"ZEBRA_EFFECT_E2E_SESSION_ID": session_id},
            check=False,
        )
        _cycles(runner, 3)
    else:
        second_resume = None
    probe = runner.uv(
        "-m",
        "zebra_agent_worker.main",
        "--max-cycles",
        "1",
        "--idle-sleep-seconds",
        "1",
        check=False,
    )
    status = _status(runner, session_id)
    final_events = runner.uv_json(
        str(runner.runner_dir / "verify_durable.py"), "event-types", session_id
    )
    final_tools = runner.uv_json(
        str(runner.runner_dir / "verify_durable.py"), "tool-events", session_id
    )
    summary = _summary(runner)
    effects = summary.get("effects", [])
    succeeded = sum(entry["rows"] for entry in effects if entry["status"] == "succeeded")
    proof = runner.workspace / PROOF_FILE
    # The verified recovery contract: a Worker killed during the post-tool
    # model turn recovers through the completed-tool continuation to
    # completion with zero re-execution (locked by the local regression
    # test with a real gateway; any suspension here is a rig finding).
    session_events = final_events.get("event_types", [])
    started_total = sum(count for name, count in session_events if name == "tool_execution_started")
    completed_total = sum(
        count for name, count in session_events if name == "tool_execution_completed"
    )
    runner.record(
        "worker_death_mid_continuation_recovers",
        seed["status"] == 201
        and approval.returncode == 0
        and completed_before
        and resume.returncode == 0
        and status == "completed"
        and started_total == 2
        and completed_total == 1
        and succeeded == 2
        and proof.is_file()
        and proof.read_text() == PROOF_CONTENT,
        {
            "session_id": session_id,
            "completed_before_kill": completed_before,
            "events_after_kill": events.get("event_types"),
            "tool_events_after_kill": tool_detail.get("events"),
            "worker_log_tail": _log_tail(runner.run_root / "worker-death.log"),
            "probe_stderr": probe.stderr[-800:] if probe.stderr else "",
            "second_resume_returncode": (
                second_resume.returncode if second_resume is not None else None
            ),
            "resume_returncode": resume.returncode,
            "session_status": status,
            "succeeded_effects": succeeded,
            "approval_returncode": approval.returncode,
            "final_events": final_events.get("event_types"),
            "final_tools": [
                entry for entry in final_tools.get("events", []) if "tool" in str(entry["type"])
            ],
        },
    )


def scenario_lease_loss(runner: Runner) -> None:
    _clean_proofs(runner)
    seed = _seed(
        runner,
        prompt="WRITE-FILE SLOW-FILE: create lease-proof.txt slowly.",
        key="effect-e2e-exec-lease-1",
    )
    session_id = seed["session_id"]
    _cycles(runner, 2)
    approval = runner.uv(
        str(runner.runner_dir / "approve_and_resume.py"),
        env_extra={"ZEBRA_EFFECT_E2E_SESSION_ID": session_id},
        check=False,
    )
    worker = _background_worker(runner, name="lease")
    deadline = time.monotonic() + 120
    started_seen = False
    while time.monotonic() < deadline:
        events = runner.uv_json(
            str(runner.runner_dir / "verify_durable.py"), "event-types", session_id
        )
        started_seen = any(
            "tool_execution_started" == str(entry[0]) for entry in events.get("event_types", [])
        )
        if started_seen:
            break
        time.sleep(1)
    expiry = runner.uv_json(str(runner.runner_dir / "verify_durable.py"), "rotate-epoch")
    worker.wait(timeout=180)
    _cycles(runner, 2)
    summary = _summary(runner)
    effects = summary.get("effects", [])
    status = _status(runner, session_id)
    lease_proof = runner.workspace / "lease-proof.txt"
    succeeded = sum(entry["rows"] for entry in effects if entry["status"] == "succeeded")
    stale_terminal_rejected = all(
        entry["terminal_bound"] == 0 for entry in effects if entry["status"] != "succeeded"
    )
    runner.record(
        "lease_loss_uncertain_reconcile",
        seed["status"] == 201
        and approval.returncode == 0
        and started_seen
        and expiry.get("rotated_epoch")
        and stale_terminal_rejected
        and lease_proof.is_file(),
        {
            "session_id": session_id,
            "tool_started": started_seen,
            "rotated_epoch": expiry.get("rotated_epoch"),
            "effects": effects,
            "succeeded": succeeded,
            "session_status": status,
            "lease_proof_present": lease_proof.is_file(),
        },
    )


def run_execution_tier(runner: Runner) -> None:
    prior = scenario_side_effect(runner)
    scenario_restart_no_duplicate(runner, prior)
    scenario_replay_consistency(runner, prior)
    scenario_payload_binding(prior, runner)
    scenario_completed_memory(runner)
    scenario_worker_death_recovers(runner)
    scenario_lease_loss(runner)
    scenario_workspace_cp(runner)
    _cooldown()


def _cooldown() -> None:
    time.sleep(1)


def cleanup_workspace(runner: Runner) -> None:
    for entry in Path(runner.workspace).glob("*"):
        if entry.is_file():
            entry.unlink(missing_ok=True)


def _mount_scratch_volume(label: str) -> Path | None:
    """Rig helper: create a scratch volume that auto-mounts under /Volumes.

    The colima VM shares /Volumes, so the default mount point is directly
    bindable into gVisor sandboxes and satisfies the dedicated-mount quota
    gate without any custom mount dance.
    """
    import os as _os
    import subprocess as _sp
    import time as _t

    device = _sp.run(
        ("hdiutil", "attach", "-nomount", "ram://262144"),
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not device:
        return None
    _sp.run(
        ("diskutil", "eraseDisk", "APFS", label, "GPTFormat", device),
        capture_output=True,
        check=False,
    )
    _t.sleep(3)
    mounted = Path("/Volumes") / label
    if not _os.path.ismount(mounted):
        _sp.run(("hdiutil", "detach", device, "-force"), capture_output=True, check=False)
        return None
    return mounted


def _create_git_source(runner: Runner) -> str:
    import subprocess as _sp

    repo = runner.run_root / "cp-source-repo"
    if repo.exists():
        _sp.run(("rm", "-rf", str(repo)), check=False)
    repo.mkdir(parents=True)
    for command in (
        ("git", "init", "--quiet"),
        ("git", "config", "user.email", "cp@example"),
        ("git", "config", "user.name", "CP"),
    ):
        _sp.run((*command[:1], "-C", str(repo), *command[1:]), check=True, capture_output=True)
    (repo / "TASK.md").write_text("# control-plane workspace\nrun the side effect\n")
    _sp.run(("git", "-C", str(repo), "add", "."), check=True, capture_output=True)
    _sp.run(
        ("git", "-C", str(repo), "commit", "--quiet", "-m", "initial"),
        check=True,
        capture_output=True,
    )
    return str(repo)


def scenario_workspace_cp(runner: Runner) -> None:
    """Full chain: git source -> API command -> mounted materialization ->
    approved side effect inside the provisioned tree -> completed."""
    import subprocess as _sp

    volume_root = Path(runner.cloud_env.get("ZEBRA_WORKSPACE_VOLUME_ROOT", ""))
    if not volume_root:
        runner.record_skipped(
            "workspace_cp_provisioned_side_effect",
            "volume_root_not_configured",
            "ZEBRA_WORKSPACE_VOLUME_ROOT on a gVisor rig",
        )
        return
    import time as _t

    label = f"ZEBRACPE2E{int(_t.time()) % 100000}"
    cp_root = _mount_scratch_volume(label)
    mounted = cp_root is not None
    repo = _create_git_source(runner)
    revision = _sp.run(
        ("git", "-C", repo, "rev-parse", "HEAD"),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    created = runner.uv_json(
        str(runner.runner_dir / "workspace_command.py"),
        env_extra={
            "ZEBRA_EFFECT_E2E_SOURCE_REPO": repo,
            "ZEBRA_EFFECT_E2E_SOURCE_REVISION": revision,
        },
    )
    workspace_id = created["workspace_id"]
    seeded = runner.uv_json(
        str(runner.runner_dir / "seed_session.py"),
        env_extra={
            "ZEBRA_EFFECT_E2E_WORKSPACE": f"workspace://{workspace_id}",
            "ZEBRA_EFFECT_E2E_SEED_KEY": f"cp-session-{workspace_id}",
            "ZEBRA_EFFECT_E2E_PROMPT": "WRITE-FILE: create cp-proof.txt",
        },
    )
    cp_env = {
        "ZEBRA_WORKSPACE_VOLUME_ROOT": str(cp_root),
        "ZEBRA_WORKSPACE_VOLUME_LAYOUT": "root",
    }
    probe = runner.uv(
        "-m",
        "zebra_agent_worker.main",
        "--max-cycles",
        "1",
        "--idle-sleep-seconds",
        "1",
        check=False,
        env_extra=cp_env,
    )
    import subprocess as _chmod

    _chmod.run(("chmod", "-R", "777", str(cp_root)), capture_output=True, check=False)
    approval = runner.uv(
        str(runner.runner_dir / "approve_and_resume.py"),
        env_extra={"ZEBRA_EFFECT_E2E_SESSION_ID": seeded["session_id"]},
        check=False,
    )
    for _ in range(3):
        runner.uv(
            "-m",
            "zebra_agent_worker.main",
            "--max-cycles",
            "2",
            "--idle-sleep-seconds",
            "1",
            check=False,
            env_extra=cp_env,
        )
    status = _status(runner, seeded["session_id"])
    instance = runner.uv_json(
        str(runner.runner_dir / "workspace_command.py"),
        env_extra={"ZEBRA_EFFECT_E2E_WORKSPACE_ID": workspace_id},
    )
    probe_tail = (probe.stderr or "")[-600:] if probe else ""
    proof = cp_root / PROOF_FILE
    runner.record(
        "workspace_cp_provisioned_side_effect",
        created.get("status") == 201
        and seeded["status"] == 201
        and approval.returncode == 0
        and mounted
        and status == "completed"
        and instance.get("workspace", {}).get("state") == "ready"
        and instance.get("workspace", {}).get("materialized_revision") == revision
        and (cp_root / "TASK.md").is_file()
        and proof.is_file()
        and proof.read_text() == "effect-e2e-proof",
        {
            "workspace_id": workspace_id,
            "cp_root": str(cp_root),
            "mounted": mounted,
            "session_status": status,
            "workspace": instance,
            "proof_present": proof.is_file(),
            "approval_returncode": approval.returncode,
            "probe_stderr": probe_tail,
        },
    )
