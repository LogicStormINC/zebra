from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_observability.live_eval_cases import case_to_json, load_live_eval_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the fixed Zebra live-eval run matrix")
    parser.add_argument("--cases", type=Path, default=Path("evals/live/cases"))
    parser.add_argument("--split", choices=("development", "holdout"))
    args = parser.parse_args()

    cases = load_live_eval_cases(args.cases)
    for case in cases:
        if args.split is not None and case.split != args.split:
            continue
        for repetition in range(1, case.repetitions + 1):
            print(
                json.dumps(
                    {
                        "schema": "zebra.live-eval-request.v1",
                        "case": case_to_json(case),
                        "repetition": repetition,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
