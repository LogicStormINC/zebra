"""Run one canonical real-service contract runner and retain its evidence."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[3]
MANIFEST = Path(__file__).with_name("runner_manifest.json")


@dataclass(frozen=True, slots=True)
class RunnerSpec:
    runner_id: str
    script: Path
    timeout_seconds: int
    evidence_env: str


def load_specs() -> dict[str, RunnerSpec]:
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if document.get("schema_version") != "zebra.cloudline.runner-manifest.v1":
        raise ValueError("unsupported real-service runner manifest")
    specs: dict[str, RunnerSpec] = {}
    for raw in document.get("runners", []):
        runner_id = _required_string(raw, "id")
        if runner_id in specs:
            raise ValueError(f"duplicate real-service runner: {runner_id}")
        script = ROOT / _required_string(raw, "script")
        timeout_seconds = raw.get("timeout_seconds")
        if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
            raise ValueError(f"invalid timeout for {runner_id}")
        evidence_env = _required_string(raw, "evidence_env")
        specs[runner_id] = RunnerSpec(
            runner_id=runner_id,
            script=script,
            timeout_seconds=timeout_seconds,
            evidence_env=evidence_env,
        )
    if not specs:
        raise ValueError("real-service runner manifest is empty")
    return specs


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"runner manifest field {key!r} must be a non-empty string")
    return value


def run(spec: RunnerSpec, evidence_dir: Path) -> int:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / "runner.log"
    result_path = evidence_dir / "result.json"
    environment = os.environ.copy()
    environment[spec.evidence_env] = str(evidence_dir)
    started = time.time()
    return_code: int | None = None
    timed_out = False
    process = subprocess.Popen(
        ["bash", str(spec.script)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=spec.timeout_seconds)
        return_code = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_group(process)
        output, _ = process.communicate()
        return_code = 124
    if return_code is None:
        return_code = process.wait()
    log_path.write_text(output, encoding="utf-8")
    sys.stdout.write(output)
    sys.stdout.flush()
    completed = time.time()
    result = {
        "schema_version": "zebra.cloudline.runner-result.v1",
        "runner": spec.runner_id,
        "script": str(spec.script.relative_to(ROOT)),
        "started_at_epoch": started,
        "completed_at_epoch": completed,
        "duration_seconds": round(completed - started, 3),
        "return_code": return_code,
        "timed_out": timed_out,
        "passed": return_code == 0 and not timed_out,
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    outcome = "PASS" if result["passed"] else "FAIL"
    print(f"ZEBRA_CLOUDLINE_RUNNER={spec.runner_id} RESULT={outcome}")
    return return_code


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", choices=sorted(load_specs()))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--evidence-dir", type=Path, default=Path("cloudline-evidence"))
    args = parser.parse_args()
    specs = load_specs()
    if args.list:
        for runner_id in sorted(specs):
            print(runner_id)
        return 0
    if args.runner is None:
        parser.error("--runner is required unless --list is used")
    return run(specs[args.runner], args.evidence_dir)


if __name__ == "__main__":
    raise SystemExit(main())
