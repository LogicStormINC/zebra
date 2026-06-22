import pytest
from agent_observability import (
    EvalGrade,
    EvalRunResult,
    LocalReleaseGate,
    ReleaseGatePolicy,
)


def _run_result(*grades: EvalGrade) -> EvalRunResult:
    return EvalRunResult(grades=grades)


def _grade(case_id: str, *, passed: bool, score: float) -> EvalGrade:
    return EvalGrade(
        case_id=case_id,
        passed=passed,
        score=score,
        reasons=() if passed else ("failed",),
    )


def test_local_release_gate_passes_when_policy_thresholds_are_met() -> None:
    result = LocalReleaseGate().evaluate(
        _run_result(
            _grade("case-1", passed=True, score=1.0),
            _grade("case-2", passed=True, score=1.0),
        )
    )

    assert result.passed is True
    assert result.pass_rate == 1.0
    assert result.average_score == 1.0
    assert result.reasons == ()


def test_local_release_gate_reports_pass_rate_and_score_failures() -> None:
    gate = LocalReleaseGate(
        policy=ReleaseGatePolicy(min_pass_rate=0.75, min_average_score=0.8)
    )

    result = gate.evaluate(
        _run_result(
            _grade("case-1", passed=True, score=1.0),
            _grade("case-2", passed=False, score=0.0),
        )
    )

    assert result.passed is False
    assert result.pass_rate == 0.5
    assert result.average_score == 0.5
    assert result.reasons == (
        "eval pass rate below release gate minimum",
        "eval average score below release gate minimum",
    )


def test_local_release_gate_rejects_empty_eval_result() -> None:
    result = LocalReleaseGate().evaluate(EvalRunResult(grades=()))

    assert result.passed is False
    assert result.reasons == ("release gate requires at least one eval result",)


def test_release_gate_policy_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError, match="min_pass_rate"):
        ReleaseGatePolicy(min_pass_rate=1.1)

    with pytest.raises(ValueError, match="min_average_score"):
        ReleaseGatePolicy(min_average_score=-0.1)
