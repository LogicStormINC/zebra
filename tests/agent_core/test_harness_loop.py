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
    assert len(result.attempt_results) == 1
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
    assert len(result.attempt_results) == 1
    assert result.events[-1].event_type is EventType.SESSION_FAILED


def test_harness_loop_persists_a_goal_bound_root_before_the_first_turn() -> None:
    captured_contexts: list[HarnessContext] = []
    result = HarnessLoop().run(
        HarnessTask(
            title="Daily journal",
            user_input="Continue today's journal.",
            goal_binding="goal_bound",
            goal_anchor_present=True,
            goal="Maintain today's daily journal.",
        ),
        lambda context: (
            captured_contexts.append(context)
            or HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.COMPLETED,
                summary="completed",
            )
        ),
        created_at=datetime(2026, 6, 19, 20, 10, tzinfo=UTC),
    )

    assert [event.event_type for event in result.events[:4]] == [
        EventType.SESSION_CREATED,
        EventType.TASK_GOAL_SET,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
    ]
    assert result.events[1].payload["goal_text"] == "Maintain today's daily journal."
    assert result.events[3].payload["goal_binding"] == "goal_bound"
    assert captured_contexts[0].session.active_goal is not None
    assert captured_contexts[0].session.active_goal.version == 1
