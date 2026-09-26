from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from agent_observability import load_live_eval_cases
from live_eval_fixture import PILOT_CASE_IDS


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the real Zebra live-eval campaign")
    parser.add_argument("--attempts", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path("evals/live/cases"))
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--repetition", type=int, choices=(1, 2, 3))
    parser.add_argument("--repetitions", type=int, choices=(1, 3), default=3)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip case/repetition pairs already recorded in the attempts JSONL",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--runner-retries", type=int, default=2)
    args = parser.parse_args()
    if args.runner_retries < 0:
        raise ValueError("runner retries must not be negative")
    root = Path(__file__).resolve().parents[1]
    cases = load_live_eval_cases(args.cases)
    selected = [
        case
        for case in cases
        if (not args.pilot or case.case_id in PILOT_CASE_IDS)
        and (not args.case_id or case.case_id in args.case_id)
    ]
    if args.pilot and not args.case_id and len(selected) != len(PILOT_CASE_IDS):
        raise ValueError("pilot case inventory is incomplete")
    completed = _recorded_attempts(args.attempts) if args.resume else set()
    failures_path = args.attempts.with_name(f"{args.attempts.stem}.failures.jsonl")
    failures = _recorded_failures(failures_path)
    with tempfile.TemporaryDirectory(prefix="zebra-live-eval-config-") as temporary:
        config_root = Path(temporary)
        runner = {
            "schema": "zebra.live-eval-runner-config.v1",
            "kind": "zebra_real_model",
            "runner_id": "zebra-local-authoritative-events-v1",
            "runtime": "zebra-cloud-agent-harness",
            "provider": "deepseek",
            "model": "deepseek-flash",
            "argv": [sys.executable, str(root / "scripts/live_eval_zebra_runner.py")],
        }
        runner_path = config_root / "runner.json"
        runner_path.write_text(json.dumps(runner), encoding="utf-8")
        for case in selected:
            verifier = {
                "schema": "zebra.live-eval-verifier-config.v1",
                "kind": "external_postcondition",
                "verifier": case.verifier,
                "argv": [sys.executable, str(root / "scripts/live_eval_verifier.py")],
            }
            verifier_path = config_root / f"{case.case_id}.json"
            verifier_path.write_text(json.dumps(verifier), encoding="utf-8")
            repetitions = (args.repetition,) if args.repetition else range(1, args.repetitions + 1)
            for repetition in repetitions:
                if (case.case_id, repetition) in completed:
                    continue
                print(f"running {case.case_id} repetition {repetition}", flush=True)
                argv = [
                        sys.executable,
                        str(root / "scripts/live_eval_run.py"),
                        "--cases",
                        str(args.cases),
                        "--case-id",
                        case.case_id,
                        "--repetition",
                        str(repetition),
                        "--runner-config",
                        str(runner_path),
                        "--verifier-config",
                        str(verifier_path),
                        "--attempts",
                        str(args.attempts),
                        "--timeout-seconds",
                        str(args.timeout_seconds),
                    ]
                key = (case.case_id, repetition)
                for retry in range(args.runner_retries + 1):
                    environment = dict(os.environ)
                    environment["ZEBRA_LIVE_EVAL_PRIOR_RUNNER_FAILURES"] = str(
                        failures.get(key, 0)
                    )
                    completed_run = subprocess.run(
                        argv,
                        cwd=root,
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if completed_run.returncode == 0:
                        break
                    failures[key] = failures.get(key, 0) + 1
                    _append_failure(
                        failures_path,
                        case_id=case.case_id,
                        repetition=repetition,
                        returncode=completed_run.returncode,
                        stderr=completed_run.stderr,
                    )
                    print(
                        f"runner failed for {case.case_id} repetition {repetition}; "
                        f"recovery {retry + 1}/{args.runner_retries}",
                        flush=True,
                    )
                    if retry == args.runner_retries:
                        raise RuntimeError(
                            f"live eval runner retries exhausted for {case.case_id} "
                            f"repetition {repetition}"
                        )
    return 0


def _recorded_attempts(path: Path) -> set[tuple[str, int]]:
    if not path.exists():
        return set()
    completed: set[tuple[str, int]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        case_id = payload.get("case_id")
        repetition = payload.get("repetition")
        if isinstance(case_id, str) and isinstance(repetition, int):
            completed.add((case_id, repetition))
    return completed


def _recorded_failures(path: Path) -> dict[tuple[str, int], int]:
    counts: dict[tuple[str, int], int] = {}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        key = (str(payload["case_id"]), int(payload["repetition"]))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _append_failure(
    path: Path,
    *,
    case_id: str,
    repetition: int,
    returncode: int,
    stderr: str,
) -> None:
    payload = {
        "schema": "zebra.live-eval-runner-failure.v1",
        "case_id": case_id,
        "repetition": repetition,
        "returncode": returncode,
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(payload, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
