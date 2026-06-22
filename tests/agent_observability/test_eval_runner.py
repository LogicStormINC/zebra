import pytest
from agent_observability import (
    EvalCase,
    LocalEvalRunner,
    ReplayResult,
)


def _case(case_id: str, min_events: int = 1) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        category="bugfix",
        title=f"Case {case_id}",
        prompt="Run the task",
        min_events=min_events,
    )


def _replay(event_count: int = 2) -> ReplayResult:
    return ReplayResult(
        session_id="session-1",
        event_count=event_count,
        tool_result_count=0,
        audit_steps=event_count,
        model_calls=0,
        total_tokens=0,
        cost_usd=0.0,
    )


def test_local_eval_runner_grades_cases_in_order() -> None:
    result = LocalEvalRunner().run(
        cases=(_case("case-1"), _case("case-2", min_events=3)),
        replays=(_replay(), _replay(event_count=2)),
    )

    assert result.total_count == 2
    assert result.pass_count == 1
    assert result.passed is False
    assert result.average_score == 0.5
    assert [grade.case_id for grade in result.grades] == ["case-1", "case-2"]
    assert result.grades[1].reasons == ("event count below case minimum",)


def test_local_eval_runner_marks_missing_replay_as_failure() -> None:
    result = LocalEvalRunner().run(
        cases=(_case("case-1"), _case("case-2")),
        replays=(_replay(),),
    )

    assert result.total_count == 2
    assert result.pass_count == 1
    assert result.grades[1].passed is False
    assert result.grades[1].reasons == ("missing replay result for eval case",)


def test_local_eval_runner_rejects_empty_cases() -> None:
    with pytest.raises(ValueError, match="at least one case"):
        LocalEvalRunner().run(cases=(), replays=())
