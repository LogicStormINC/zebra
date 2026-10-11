"""Incremental actual-run collector; input environment secrets never enter reports."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import monotonic
from typing import Any

from joint_acceptance import run_joint
from joint_business_seed import validate_seed
from joint_timing import aggregate_timings


def collect(output: Path, seed: dict[str, Any], *, count: int = 100, seconds: int = 3600) -> int:
    if not 100 <= count <= 1000 or not 60 <= seconds <= 3600:
        raise ValueError("collector count/time budget outside bounded range")
    validate_seed(seed)
    output.mkdir(parents=True, exist_ok=False)
    deadline = monotonic() + seconds
    samples = []
    failure = None
    for index in range(count):
        remaining = deadline - monotonic()
        if remaining < 65:
            failure = "collector_total_deadline"
            break
        environment = dict(os.environ)
        environment["ZEBRA_E2E_COMMIT_VISIBILITY"] = "1"
        environment["ZEBRA_E2E_TIMEOUT_SECONDS"] = str(min(300, int(remaining - 60)))
        # The existing bounded runner owns isolation, mutations and terminal cleanup.
        # This collector does not change models, renew grants or restart the application.
        destination = output / f"sample-{index:04d}"
        # Simple answers deliberately have no intermediate commentary; their
        # separate matrix case must not dilute task-communication measurements.
        case = ("multi_source", "tool_only")[index % 2]
        run_joint(environment, destination, case_id=case, business_seed=seed)
        result = json.loads((destination / "joint-result.json").read_text())
        if result.get("status") != "slice_passed":
            failure = result.get("reason", "joint_slice_not_passed")
            break
        evidence = json.loads((destination / (case.replace("_", "-") + ".json")).read_text())
        candidate = {"source_identity": result["source_identity"], "browser": evidence}
        try:
            summary = aggregate_timings([*samples, candidate])
        except ValueError as error:
            failure = str(error)
            break
        samples.append(candidate)
        (output / "timing-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    summary = (
        aggregate_timings(samples)
        if failure is None
        else {
            "healthy_samples": len(samples),
            "status": "blocked",
            "reason": failure,
            "full_goal_passed": False,
        }
    )
    (output / "timing-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    # Missing cross-clock/matrix evidence never becomes a full release pass.
    return 0 if summary.get("timing_passed") is True else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seconds", type=int, default=3600)
    args = parser.parse_args()
    raise SystemExit(
        collect(
            args.output, json.loads(args.seed.read_text()), count=args.count, seconds=args.seconds
        )
    )
