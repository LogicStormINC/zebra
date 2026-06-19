from datetime import UTC, datetime

from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessLoop,
    HarnessStopReason,
    HarnessTask,
)


def test_harness_loop_retries_and_stops_after_success() -> None:
    loop = HarnessLoop()
    task = HarnessTask(
        title="Retry until success",
        user_input="fix after one retry",
        max_attempts=2,
    )

    def attempt_runner(context: HarnessContext) -> HarnessAttemptResult:
        attempt_number = context.attempt.number
        if attempt_number == 1:
            return HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="first attempt failed",
            )
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="second attempt succeeded",
        )

    result = loop.run(
        task,
        attempt_runner,
        created_at=datetime(2026, 6, 19, 23, 0, tzinfo=UTC),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert len(result.attempt_results) == 2
    assert result.run_result.attempts_used == 2
    assert result.run_result.stop_reason is HarnessStopReason.COMPLETED
    assert [
        event.event_type for event in result.events
    ].count(EventType.HARNESS_ATTEMPT_STARTED) == 2
    assert result.events[-1].event_type is EventType.SESSION_COMPLETED


def test_harness_loop_stops_when_retry_budget_is_exhausted() -> None:
    loop = HarnessLoop()
    task = HarnessTask(title="Exhaust retries", user_input="keep failing", max_attempts=2)

    result = loop.run(
        task,
        lambda _context: HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="attempt failed",
        ),
        created_at=datetime(2026, 6, 19, 23, 5, tzinfo=UTC),
    )

    assert result.session.status is SessionStatus.FAILED
    assert len(result.attempt_results) == 2
    assert result.run_result.attempts_used == 2
    assert result.run_result.can_retry is False
    assert result.run_result.stop_reason is HarnessStopReason.RETRY_EXHAUSTED
    assert [
        event.event_type for event in result.events
    ].count(EventType.HARNESS_ATTEMPT_STARTED) == 2
    assert result.events[-1].event_type is EventType.SESSION_FAILED
