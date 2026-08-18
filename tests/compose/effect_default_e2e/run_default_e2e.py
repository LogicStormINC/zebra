"""CLOUD-EFFECT-DEFAULT-E2E-01: default-entrypoint real side-effect acceptance.

Composition tier (always executed against real PostgreSQL and MinIO):

- migrations and control-plane epoch bootstrap succeed
- a queued session is accepted through the committed API application object
- the default Worker entrypoint claims the session under a fenced lease
- when no gVisor engine is reachable the Worker fails closed before any model
  call or Effect intent, the session stays recoverable, repeated cycles stay
  idempotent, and no SQLite authority file appears anywhere
- the API handoff Effect read port answers cleanly on the cloud bundle

Execution tier (criteria 1-5 and 8 of the closeout plan) additionally requires
a gVisor-capable engine and a dedicated workspace mount; those scenarios stay
explicitly skipped until that infrastructure exists. The runner never claims
the execution tier from composition-tier evidence.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RUNNER_DIR = ROOT / "tests/compose/effect_default_e2e"
PROJECT = "zebra-effect-default-e2e"
POSTGRES_PORT = 25497
MINIO_PORT = 25496
STUB_PORT = 25495
EVIDENCE_DIR = Path(
    os.environ.get("ZEBRA_EFFECT_DEFAULT_E2E_EVIDENCE_DIR", "/tmp/zebra-effect-default-e2e")
)
EXECUTION_TIER_SCENARIOS = (
    "side_effect_schedule_claim_complete",
    "payload_object_binding",
    "replay_consistency",
    "worker_restart_no_duplicate",
    "lease_loss_uncertain_reconcile",
    "session_completed_governed_memory",
    "worker_death_mid_continuation_recovers",
)

CLOUD_ENV = {
    "ZEBRA_PROFILE": "cloud",
    "ZEBRA_DATABASE_URL": f"postgresql://zebra:zebra-effect-e2e-password@127.0.0.1:{POSTGRES_PORT}/zebra",
    "ZEBRA_RUNTIME_CLASS": "gvisor",
    "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
    "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
    "ZEBRA_DEPLOYMENT_NAMESPACE": "effect-default-e2e",
    "ZEBRA_AUTHORITY_ISSUER": "https://effect-e2e-authority.example",
    "ZEBRA_HISTORY_SCOPE_NAMESPACE": "effect-e2e-history",
    "ZEBRA_CONTINUATION_SCOPE_NAMESPACE": "effect-e2e-continuation",
    "ZEBRA_MEMORY_CURSOR_SIGNING_KEY": "effect-e2e-memory-cursor-key-32-bytes",
    "ZEBRA_S3_ENDPOINT": f"http://127.0.0.1:{MINIO_PORT}",
    "ZEBRA_S3_BUCKET": "zebra-artifacts",
    "ZEBRA_S3_ACCESS_KEY": "zebra-effect-e2e",
    "ZEBRA_S3_SECRET_KEY": "zebra-effect-e2e-secret",
    "ZEBRA_S3_REGION": "us-east-1",
    "ZEBRA_MODEL_PROVIDER": "effect-e2e-stub",
    "ZEBRA_MODEL_BASE_URL": f"http://127.0.0.1:{STUB_PORT}",
    "ZEBRA_MODEL_API_KEY_ENV": "ZEBRA_EFFECT_E2E_STUB_KEY",
    "ZEBRA_EFFECT_E2E_STUB_KEY": "stub-key",
    "ZEBRA_MODEL_NAME": "effect-e2e-stub",
}


class Runner:
    def __init__(self) -> None:
        self.scenarios: dict[str, dict[str, Any]] = {}
        self.failures = 0
        self.stub_process: subprocess.Popen[bytes] | None = None
        self.run_root = Path(EVIDENCE_DIR)
        self.runner_dir = RUNNER_DIR
        self.project_root = ROOT
        self.cloud_env = CLOUD_ENV
        self.workspace = Path(
            os.environ.get("ZEBRA_EFFECT_E2E_WORKSPACE", str(self.run_root / "workspace"))
        )
        runtime_image = os.environ.get("ZEBRA_EFFECT_E2E_RUNTIME_IMAGE")
        if runtime_image:
            CLOUD_ENV["ZEBRA_RUNTIME_IMAGE"] = runtime_image
        volume_root = os.environ.get("ZEBRA_WORKSPACE_VOLUME_ROOT", "").strip()
        if volume_root:
            CLOUD_ENV["ZEBRA_WORKSPACE_VOLUME_ROOT"] = volume_root

    def record(self, name: str, passed: bool, detail: dict[str, Any]) -> None:
        status = "pass" if passed else "fail"
        self.scenarios[name] = {"status": status, **detail}
        if not passed:
            self.failures += 1
        print(f"scenario {name}: {status}")

    def record_skipped(self, name: str, reason: str, requirement: str) -> None:
        self.scenarios[name] = {
            "status": "skipped",
            "reason": reason,
            "requires": requirement,
        }
        print(f"scenario {name}: skipped ({reason})")

    def compose(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        # Dependencies always run on the local default engine; only the
        # Worker's runtime engine may point at a remote gVisor rig through
        # DOCKER_HOST in the ambient environment.
        env = {key: value for key, value in os.environ.items() if key != "DOCKER_HOST"}
        return subprocess.run(
            (
                "docker",
                "compose",
                "--project-name",
                PROJECT,
                "--file",
                str(RUNNER_DIR / "compose.yml"),
                *args,
            ),
            capture_output=True,
            text=True,
            env=env,
        )

    def uv(
        self, *args: str, env_extra: dict[str, str] | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        env = {**os.environ, **CLOUD_ENV, **(env_extra or {})}
        result = subprocess.run(
            ("uv", "run", "--project", str(ROOT), "python", *args),
            cwd=self.run_root,
            env=env,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"command failed ({result.returncode}): {args}\n{result.stderr[-2000:]}"
            )
        return result

    def uv_json(self, *args: str, env_extra: dict[str, str] | None = None) -> dict[str, Any]:
        result = self.uv(*args, env_extra=env_extra)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def start_dependencies(self) -> None:
        up = self.compose("up", "--detach", "--wait", "postgres", "minio")
        if up.returncode != 0:
            raise RuntimeError(f"dependencies failed: {up.stderr[-1000:]}")
        init = self.compose("run", "--rm", "minio-init")
        if init.returncode != 0:
            raise RuntimeError(f"minio-init failed: {init.stderr[-1000:]}")

    def stop_dependencies(self) -> None:
        self.compose("down", "--volumes", "--remove-orphans")

    def start_stub(self) -> None:
        self.stub_process = subprocess.Popen(
            (
                "uv",
                "run",
                "--project",
                str(ROOT),
                "python",
                str(RUNNER_DIR / "stub_model.py"),
                str(STUB_PORT),
            ),
            cwd=self.run_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(40):
            probe = subprocess.run(
                (
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "-X",
                    "POST",
                    f"http://127.0.0.1:{STUB_PORT}/chat/completions",
                    "-H",
                    "Content-Type: application/json",
                    "-d",
                    "{}",
                ),
                capture_output=True,
                text=True,
            )
            if probe.stdout.strip() == "200":
                return
            time.sleep(0.25)
        raise RuntimeError("stub model server did not become ready")

    def stop_stub(self) -> None:
        if self.stub_process is not None:
            self.stub_process.send_signal(signal.SIGTERM)
            self.stub_process.wait(timeout=10)
            self.stub_process = None

    def scenario_infrastructure(self) -> None:
        migration = self.uv(str(ROOT / "docker/migrate.py"), check=False)
        epoch = self.uv_json(str(RUNNER_DIR / "verify_durable.py"), "bootstrap-epoch")
        sqlite_files = _find_sqlite(self.run_root)
        try:
            leases = self.uv_json(str(RUNNER_DIR / "verify_durable.py"), "lease-rows")
        except RuntimeError:
            leases = {"lease_rows": None, "lease_epochs": None}
        self.record(
            "infrastructure",
            migration.returncode == 0 and not sqlite_files and epoch.get("epoch"),
            {
                "migrations": "applied" if migration.returncode == 0 else migration.stderr[-500:],
                "epoch": epoch.get("epoch"),
                "sqlite_files": sqlite_files,
                "lease_rows": leases.get("lease_rows"),
            },
        )

    def scenario_session_acceptance(self) -> dict[str, Any]:
        seed = self.uv_json(
            str(RUNNER_DIR / "seed_session.py"),
            env_extra={
                "ZEBRA_EFFECT_E2E_WORKSPACE": str(self.workspace),
                "ZEBRA_EFFECT_E2E_SEED_KEY": "effect-default-e2e-seed-1",
                "ZEBRA_EFFECT_E2E_PROMPT": "WRITE-FILE: create effect-proof.txt",
            },
        )
        status = self.uv_json(
            str(RUNNER_DIR / "verify_durable.py"), "session-status", seed["session_id"]
        )
        self.record(
            "session_acceptance",
            seed["status"] == 201 and status["status"] == "ready",
            {"seed_status": seed["status"], "projection_status": status["status"]},
        )
        return seed

    def _run_worker_cycle(self) -> subprocess.CompletedProcess[bytes]:
        return self.uv(
            "-m",
            "zebra_agent_worker.main",
            "--max-cycles",
            "1",
            "--lease-ttl-seconds",
            "4",
            "--idle-sleep-seconds",
            "1",
            check=False,
        )

    def scenario_worker_fail_closed(self, session_id: str) -> None:
        first = self._run_worker_cycle()
        first_reason = _fail_closed_reason(first)
        effects_first = self.uv_json(str(RUNNER_DIR / "verify_durable.py"), "effect-outbox-count")
        status_first = self.uv_json(
            str(RUNNER_DIR / "verify_durable.py"), "session-status", session_id
        )
        events_first = self.uv_json(
            str(RUNNER_DIR / "verify_durable.py"), "event-types", session_id
        )
        time.sleep(5)
        second = self._run_worker_cycle()
        second_reason = _fail_closed_reason(second)
        effects_second = self.uv_json(str(RUNNER_DIR / "verify_durable.py"), "effect-outbox-count")
        sqlite_files = _find_sqlite(self.run_root)
        tool_events = [
            entry
            for entry in events_first.get("event_types", [])
            if "TOOL" in str(entry[0]).upper()
        ]
        self.record(
            "worker_fail_closed",
            bool(first_reason)
            and bool(second_reason)
            and effects_first["effect_outbox_rows"] == 0
            and effects_second["effect_outbox_rows"] == 0
            and status_first["status"] == "ready"
            and not tool_events
            and not sqlite_files,
            {
                "first_reason": first_reason,
                "second_reason": second_reason,
                "effect_outbox_rows": effects_second["effect_outbox_rows"],
                "session_status": status_first["status"],
                "tool_events": tool_events,
                "sqlite_files": sqlite_files,
            },
        )

    def scenario_handoff_effect_read(self, session_id: str) -> None:
        read = self.uv_json(str(RUNNER_DIR / "verify_durable.py"), "handoff-read", session_id)
        self.record(
            "handoff_effect_read",
            read.get("terminal_keys") == [] and read.get("has_uncertain") is False,
            read,
        )

    def gvisor_available(self) -> bool:
        info = subprocess.run(
            ("docker", "info", "--format", "{{json .Runtimes}}"),
            capture_output=True,
            text=True,
        )
        return '"runsc"' in info.stdout

    def run(self) -> int:
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        result: dict[str, Any] = {
            "schema_version": "zebra.effect-default-e2e.v1",
            "runner": "CLOUD-EFFECT-DEFAULT-E2E-01",
            "scenarios": self.scenarios,
            "passed": False,
        }
        try:
            self.start_dependencies()
            self.start_stub()
            seed: dict[str, Any] = {}
            execution_enabled = (
                self.gvisor_available()
                and os.environ.get("ZEBRA_EFFECT_E2E_ENABLE_EXECUTION_TIER") == "1"
            )
            composition_actions: list[tuple[str, Any]] = [
                ("infrastructure", lambda: self.scenario_infrastructure()),
                ("session_acceptance", lambda: seed.update(self.scenario_session_acceptance())),
                (
                    "handoff_effect_read",
                    lambda: self.scenario_handoff_effect_read(seed["session_id"]),
                ),
            ]
            if not execution_enabled:
                composition_actions.append(
                    (
                        "worker_fail_closed",
                        lambda: self.scenario_worker_fail_closed(seed["session_id"]),
                    )
                )
            for name, action in composition_actions:
                try:
                    action()
                except Exception as error:  # noqa: BLE001 - evidence must record the failure
                    self.record(name, False, {"error": repr(error)})
            if "session_id" not in seed:
                for name in ("worker_fail_closed", "handoff_effect_read"):
                    if name not in self.scenarios:
                        self.record(
                            name,
                            False,
                            {"error": "session seed failed; dependent scenario not executed"},
                        )
            if not execution_enabled:
                reason = (
                    "gvisor_engine_absent"
                    if not self.gvisor_available()
                    else "execution_tier_not_enabled"
                )
                for name in EXECUTION_TIER_SCENARIOS:
                    self.record_skipped(
                        name,
                        reason,
                        (
                            "gVisor-capable engine, dedicated workspace mount,"
                            " execution tier enablement"
                        ),
                    )
            else:
                from execution_tier import run_execution_tier

                try:
                    run_execution_tier(self)
                except Exception as error:  # noqa: BLE001 - evidence must record the failure
                    self.record("execution_tier", False, {"error": repr(error)})
            result["scenarios"] = self.scenarios
            result["passed"] = self.failures == 0 and execution_enabled
            _write_result(self.run_root, result)
            if self.failures:
                print("ZEBRA_EFFECT_DEFAULT_E2E=FAIL")
                return 1
            if not execution_enabled:
                print("ZEBRA_EFFECT_DEFAULT_E2E=BLOCKED")
                return 2
            print("ZEBRA_EFFECT_DEFAULT_E2E=PASS")
            return 0
        finally:
            self.stop_stub()
            self.stop_dependencies()


def _fail_closed_reason(completed: subprocess.CompletedProcess[bytes]) -> str | None:
    if completed.returncode == 0:
        return None
    for known in (
        "workspace quota requires the workspace root to be a dedicated mount point",
        "OCI engine does not advertise runtime runsc",
    ):
        if known in completed.stderr:
            return known
    return completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "unknown"


def _find_sqlite(root: Path) -> list[str]:
    return [
        str(path)
        for path in root.rglob("*")
        if path.is_file() and (path.suffix in {".sqlite", ".sqlite3"} or ".sqlite" in path.name)
    ]


def _write_result(evidence_dir: Path, result: dict[str, Any]) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    return Runner().run()


if __name__ == "__main__":
    sys.exit(main())
