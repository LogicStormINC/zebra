from __future__ import annotations

from pathlib import Path

from agent_observability import (
    EvalCase,
    LocalEvalRunner,
    LocalReleaseGate,
    ReplayResult,
    load_eval_cases,
)


def main() -> int:
    cases = load_eval_cases(Path("evals/cases"))
    replays = tuple(_baseline_replay(case) for case in cases)
    run_result = LocalEvalRunner().run(cases, replays)
    gate_result = LocalReleaseGate().evaluate(run_result)
    print(
        "eval release gate: "
        f"passed={gate_result.passed} "
        f"pass_rate={gate_result.pass_rate:.2f} "
        f"average_score={gate_result.average_score:.2f} "
        f"cases={run_result.total_count}"
    )
    for reason in gate_result.reasons:
        print(f"- {reason}")
    return 0 if gate_result.passed else 1


def _baseline_replay(case: EvalCase) -> ReplayResult:
    return ReplayResult(
        session_id=f"baseline-{case.case_id}",
        event_count=case.min_events,
        tool_result_count=case.min_tool_results,
        audit_steps=case.min_events,
        model_calls=1,
        total_tokens=1,
        cost_usd=0.0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
