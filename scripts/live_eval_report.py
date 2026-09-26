from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agent_observability import (
    build_live_eval_report,
    load_live_eval_attempts,
    load_live_eval_cases,
)

try:
    from scripts.live_eval_fixture import PILOT_CASE_IDS
except ModuleNotFoundError:
    from live_eval_fixture import PILOT_CASE_IDS


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate externally verified Zebra live-eval attempts"
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("evals/live/cases"),
        help="directory containing the fixed live-eval case manifests",
    )
    parser.add_argument(
        "--attempts", required=True, type=Path, help="JSONL file containing verified attempts"
    )
    parser.add_argument(
        "--evidence-tier",
        choices=("real_dependency", "real_model"),
        default="real_model",
    )
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="report only the fixed 12-case pilot matrix",
    )
    parser.add_argument(
        "--failures",
        type=Path,
        help="runner-failure JSONL; defaults to <attempts-stem>.failures.jsonl",
    )
    args = parser.parse_args()
    cases = load_live_eval_cases(args.cases)
    if args.pilot:
        cases = tuple(case for case in cases if case.case_id in PILOT_CASE_IDS)
    report = build_live_eval_report(
        cases,
        load_live_eval_attempts(args.attempts),
        evidence_tier=args.evidence_tier,
    )
    payload = asdict(report)
    failures_path = args.failures or args.attempts.with_name(
        f"{args.attempts.stem}.failures.jsonl"
    )
    payload.update(_runner_failure_summary(failures_path))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.complete else 2


def _runner_failure_summary(path: Path) -> dict[str, int]:
    failures = 0
    recovered: set[tuple[str, int]] = set()
    if path.is_file():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                recovered.add((str(payload["case_id"]), int(payload["repetition"])))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid live eval runner failure at line {line_number}"
                ) from exc
            failures += 1
    return {
        "runner_process_failure_count": failures,
        "runner_recovered_attempt_count": len(recovered),
    }


if __name__ == "__main__":
    raise SystemExit(main())
