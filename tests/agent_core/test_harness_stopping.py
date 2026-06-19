from datetime import UTC, datetime

from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessLoop,
    HarnessStoppingPolicy,
    HarnessStopReason,
    HarnessTask,
)


def test_stopping_policy_allows_retry_for_failed_non_terminal_attempt() -> None:
    policy = HarnessStoppingPolicy()
    task = HarnessTask(title="Retryable task", user_input="retry this", max_attempts=2)
    attempt_result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="first attempt failed",
    )

    run_result = policy.build_run_result(task, attempts_used=1, attempt_result=attempt_result)

    assert run_result.can_retry is True
    assert run_result.stop_reason is HarnessStopReason.RETRY_ALLOWED
    assert run_result.attempts_used == 1


def test_stopping_policy_marks_retry_exhausted_when_limit_reached() -> None:
    policy = HarnessStoppingPolicy()
    task = HarnessTask(title="Terminal task", user_input="stop now", max_attempts=1)
    attempt_result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.FAILED,
        summary="attempt failed",
    )

    run_result = policy.build_run_result(task, attempts_used=1, attempt_result=attempt_result)

    assert run_result.can_retry is False
    assert run_result.stop_reason is HarnessStopReason.RETRY_EXHAUSTED


def test_harness_loop_exposes_structured_run_result() -> None:
    loop = HarnessLoop()
    task = HarnessTask(title="One-shot success", user_input="complete immediately")

    result = loop.run(
        task,
        lambda _context: HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="done",
        ),
        created_at=datetime(2026, 6, 19, 22, 30, tzinfo=UTC),
    )

    assert result.run_result.final_outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.stop_reason is HarnessStopReason.COMPLETED
    assert result.run_result.can_retry is False
    assert result.run_result.summary == "done"
