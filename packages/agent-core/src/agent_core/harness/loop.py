from collections.abc import Callable
from datetime import datetime

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.sessions import Session
from agent_core.harness.models import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessLoopResult,
    HarnessTask,
)
from agent_core.harness.recorder import HarnessEventRecorder
from agent_core.harness.stopping import HarnessStoppingPolicy
from agent_core.harness.timing import SystemClock
from agent_core.ports.clock import ClockPort

AttemptRunner = Callable[[HarnessContext], HarnessAttemptResult]


class HarnessLoop:
    def __init__(
        self,
        *,
        stopping_policy: HarnessStoppingPolicy | None = None,
        clock: ClockPort | None = None,
    ) -> None:
        self._stopping_policy = stopping_policy or HarnessStoppingPolicy()
        self._clock = clock or SystemClock()

    def run(
        self,
        task: HarnessTask,
        attempt_runner: AttemptRunner,
        *,
        created_at: datetime | None = None,
    ) -> HarnessLoopResult:
        started_at = created_at or self._clock.now()
        session = Session.create(title=task.title, created_at=started_at)
        recorder = HarnessEventRecorder(session=session, clock=self._clock)

        recorder.record(
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": task.title},
            created_at=started_at,
        )
        recorder.record(
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": task.user_input},
        )
        recorder.record(
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": task.title, "user_input": task.user_input},
        )
        attempt_results: list[HarnessAttemptResult] = []

        for attempt_number in range(1, task.max_attempts + 1):
            attempt_started_at = self._clock.now()
            attempt = HarnessAttempt(number=attempt_number, started_at=attempt_started_at)
            recorder.record(
                event_type=EventType.HARNESS_ATTEMPT_STARTED,
                actor=EventActor.HARNESS,
                payload={"attempt_number": attempt.number},
                created_at=attempt_started_at,
            )

            attempt_result = attempt_runner(
                HarnessContext(task=task, session=recorder.session, attempt=attempt)
            )
            attempt_results.append(attempt_result)
            for draft in attempt_result.emitted_events:
                recorder.record_draft(draft)

            run_result = self._stopping_policy.build_run_result(
                task,
                attempts_used=attempt.number,
                attempt_result=attempt_result,
            )
            if run_result.can_retry:
                continue

            terminal_event_type = (
                EventType.SESSION_COMPLETED
                if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
                else EventType.SESSION_FAILED
            )
            recorder.record(
                event_type=terminal_event_type,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": attempt.number,
                    "summary": attempt_result.summary,
                    "metadata": attempt_result.metadata,
                },
            )
            return HarnessLoopResult(
                session=recorder.session,
                events=tuple(recorder.events),
                attempt_result=attempt_result,
                attempt_results=tuple(attempt_results),
                run_result=run_result,
            )

        raise RuntimeError("harness loop exited without producing a terminal run result")
