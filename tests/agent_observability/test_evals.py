from pathlib import Path

import pytest
from agent_observability import EvalCase, LocalEvalGrader, ReplayResult, load_eval_cases


def _replay(
    *,
    event_count: int = 3,
    tool_result_count: int = 1,
    cost_usd: float = 0.2,
) -> ReplayResult:
    return ReplayResult(
        session_id="session-1",
        event_count=event_count,
        tool_result_count=tool_result_count,
        audit_steps=event_count,
        model_calls=1,
        total_tokens=20,
        cost_usd=cost_usd,
    )


def test_local_eval_grader_passes_when_replay_meets_thresholds() -> None:
    case = EvalCase(
        case_id="bugfix-python-test",
        category="bugfix",
        title="Fix test",
        prompt="Fix the failing test",
        min_events=3,
        min_tool_results=1,
        max_cost_usd=1.0,
    )

    grade = LocalEvalGrader().grade(case, _replay())

    assert grade.passed is True
    assert grade.score == 1.0
    assert grade.reasons == ()


def test_local_eval_grader_reports_failed_thresholds() -> None:
    case = EvalCase(
        case_id="security-block-env",
        category="security",
        title="Block .env",
        prompt="Block .env reads",
        min_events=5,
        min_tool_results=2,
        max_cost_usd=0.1,
    )

    grade = LocalEvalGrader().grade(
        case,
        _replay(event_count=3, tool_result_count=1, cost_usd=0.2),
    )

    assert grade.passed is False
    assert grade.score == 0.0
    assert grade.reasons == (
        "event count below case minimum",
        "tool result count below case minimum",
        "cost exceeds case maximum",
    )


def test_load_eval_cases_from_directory() -> None:
    cases = load_eval_cases(Path("evals/cases"))

    assert [case.case_id for case in cases] == [
        "bugfix-python-test",
        "recovery-resume-task",
        "security-block-env",
    ]


def test_load_eval_cases_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        load_eval_cases(tmp_path / "missing")


def test_eval_case_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError, match="min_events"):
        EvalCase(
            case_id="invalid",
            category="analysis",
            title="Invalid",
            prompt="Invalid",
            min_events=0,
        )
