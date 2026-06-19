from datetime import UTC, datetime

from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessLoop,
    HarnessTask,
)


def test_harness_loop_runs_single_completed_attempt() -> None:
    loop = HarnessLoop()
    task = HarnessTask(title="Fix failing test", user_input="Please fix the failing test.")

    captured_contexts: list[HarnessContext] = []

    def attempt_runner(context: HarnessContext) -> HarnessAttemptResult:
        captured_contexts.append(context)
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="completed minimal harness run",
            metadata={"tool_capable": True},
        )

    result = loop.run(
        task,
        attempt_runner,
        created_at=datetime(2026, 6, 19, 20, 0, tzinfo=UTC),
    )

    assert len(captured_contexts) == 1
    assert captured_contexts[0].session.status is SessionStatus.RUNNING
    assert captured_contexts[0].attempt.number == 1
    assert result.session.status is SessionStatus.COMPLETED
    assert [event.event_type for event in result.events] == [
        EventType.SESSION_CREATED,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
        EventType.HARNESS_ATTEMPT_STARTED,
        EventType.SESSION_COMPLETED,
    ]
    assert result.events[-1].payload["summary"] == "completed minimal harness run"


def test_harness_loop_marks_failed_attempts_as_failed() -> None:
    loop = HarnessLoop()
    task = HarnessTask(title="Investigate error", user_input="Reproduce the runtime issue.")

    result = loop.run(
        task,
        lambda _context: HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="attempt failed deterministically",
        ),
        created_at=datetime(2026, 6, 19, 20, 5, tzinfo=UTC),
    )

    assert result.session.status is SessionStatus.FAILED
    assert result.events[-1].event_type is EventType.SESSION_FAILED
