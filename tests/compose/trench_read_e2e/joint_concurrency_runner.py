"""QA-only serial real SSE grid; invoke only after the shared scratch window clears."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from joint_concurrency_cases import HISTORIES, OBSERVERS, run_concurrency_case
from run_acceptance import REQUIRED_ENV
from support import Config, E2EError, load_config


def load_private_config(path: Path) -> Config:
    if path.stat().st_size > 32768 or path.stat().st_mode & 0o077:
        raise ValueError("private_bounded_inputs_required")
    inputs = json.loads(path.read_text())
    for key in ("TRENCH_E2E_BUSINESS_SNAPSHOT_URL", "ZEBRA_E2E_WORKER_RESTART_URL"):
        inputs.setdefault(key, inputs["TRENCH_E2E_BFF_URL"])
    inputs.setdefault("TRENCH_E2E_EVENT_ID", "unused_in_concurrency")
    return load_config(inputs, REQUIRED_ENV)


def failure_codes(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        return sorted({code for leaf in exc.exceptions for code in failure_codes(leaf)})
    return [exc.code if isinstance(exc, E2EError) else type(exc).__name__]


async def run_serial(
    config: Config, conversation: str, output: Path, *, pilot: bool
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    dimensions = [(1000, 1)] if pilot else [(h, n) for h in HISTORIES for n in OBSERVERS]
    summary: dict[str, Any] = {
        "status": "running",
        "cells": [],
        "expected_cells": len(dimensions),
        "history_basis": "metadata_only_not_semantic_capacity",
        "full_goal_passed": False,
    }
    for history, observers in dimensions:
        cell: dict[str, Any] = {"history_floor": history, "observer_count": observers}
        try:
            evidence = await run_concurrency_case(
                config, conversation, history=history, observers=observers
            )
            cell["status"] = "passed"
            cell["evidence"] = f"history-{history}-observers-{observers}.json"
            (output / cell["evidence"]).write_text(json.dumps(evidence, indent=2) + "\n")
        except Exception as exc:
            # A failed Turn may remain active. Stop rather than overlap another cell.
            cell.update(status="blocked", reasons=failure_codes(exc))
        summary["cells"].append(cell)
        summary["status"] = (
            "blocked"
            if cell["status"] != "passed"
            else "passed"
            if len(summary["cells"]) == len(dimensions)
            else "running"
        )
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(cell), flush=True)
        if cell["status"] != "passed":
            break
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--conversation", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pilot", action="store_true", help="Only 1k history / 1 observer")
    args = parser.parse_args()
    try:
        if not 0 < len(args.conversation) <= 256 or "::" in args.conversation:
            raise ValueError("invalid_conversation")
        summary = asyncio.run(
            run_serial(
                load_private_config(args.inputs), args.conversation, args.output, pilot=args.pilot
            )
        )
        return 0 if summary["status"] == "passed" else 2
    except Exception as exc:
        print(json.dumps({"status": "blocked", "reasons": failure_codes(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
