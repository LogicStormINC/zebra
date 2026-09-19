"""Run one release gate and write a credential-free evidence envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCHEMA = "zebra.cloud-gate-result.v1"


def _git(*args: str) -> str:
    result = subprocess.run(
        ("git", *args), cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _version(command: tuple[str, ...]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0][:200] if result.returncode == 0 and value else None


def _base(gate: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA,
        "gate": gate,
        "candidate_sha": _git("rev-parse", "HEAD"),
        "worktree_clean": not bool(_git("status", "--porcelain")),
        "versions": {
            "python": platform.python_version(),
            "docker": _version(("docker", "version", "--format", "{{.Server.Version}}")),
        },
        "digests": {
            "uv_lock": _digest(ROOT / "uv.lock"),
            "application_compose": _digest(ROOT / "docker/compose.application.yml"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--not-enabled")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if bool(args.not_enabled) == bool(args.command):
        parser.error("provide exactly one command or --not-enabled")
    started = time.time()
    result = _base(args.gate)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    if args.not_enabled:
        return_code = 0
        result.update(
            status="NOT_ENABLED",
            reason=args.not_enabled,
            command_sha256=None,
        )
    else:
        if args.timeout_seconds <= 0:
            parser.error("--timeout-seconds must be positive")
        process = subprocess.Popen(tuple(args.command), cwd=ROOT, start_new_session=True)
        try:
            return_code = process.wait(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            return_code = 124
        result.update(
            status="PASS" if return_code == 0 else "FAIL",
            reason="timeout" if return_code == 124 else None,
            command_sha256=hashlib.sha256(
                json.dumps(args.command, separators=(",", ":")).encode()
            ).hexdigest(),
        )
    result.update(
        started_at_epoch=started,
        completed_at_epoch=time.time(),
        duration_seconds=round(time.time() - started, 3),
        return_code=return_code,
    )
    output = args.evidence_dir / "gate-result.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ZEBRA_CLOUD_GATE={args.gate} STATUS={result['status']} EVIDENCE={output}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
