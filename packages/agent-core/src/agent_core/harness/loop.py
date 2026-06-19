from collections.abc import Callable
from datetime import UTC, datetime

from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_core.harness.models import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessLoopResult,
    HarnessTask,
)

AttemptRunner = Callable[[HarnessContext], HarnessAttemptResult]


class HarnessLoop:
    def run(
        self,
        task: HarnessTask,
        attempt_runner: AttemptRunner,
        *,
        created_at: datetime | None = None,
    ) -> HarnessLoopResult:
        now = created_at or datetime.now(UTC)
        session = Session.create(title=task.title, created_at=now)
        events: list[SessionEvent] = []

        session = self._append_event(
            session,
            events,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": task.title},
            created_at=now,
        )
        session = self._append_event(
            session,
            events,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": task.user_input},
            created_at=now,
        )
        session = self._append_event(
            session,
            events,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": task.title, "user_input": task.user_input},
            created_at=now,
        )

        attempt = HarnessAttempt(number=1, started_at=now)
        session = self._append_event(
            session,
            events,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": attempt.number},
            created_at=now,
        )

        attempt_result = attempt_runner(HarnessContext(task=task, session=session, attempt=attempt))
        for draft in attempt_result.emitted_events:
            session = self._append_event(
                session,
                events,
                event_type=draft.event_type,
                actor=draft.actor,
                payload=draft.payload,
                created_at=now,
            )
        terminal_event_type = (
            EventType.SESSION_COMPLETED
            if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
            else EventType.SESSION_FAILED
        )
        session = self._append_event(
            session,
            events,
            event_type=terminal_event_type,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": attempt.number,
                "summary": attempt_result.summary,
                "metadata": attempt_result.metadata,
            },
            created_at=now,
        )
        return HarnessLoopResult(
            session=session,
            events=tuple(events),
            attempt_result=attempt_result,
        )

    @staticmethod
    def _append_event(
        session: Session,
        events: list[SessionEvent],
        *,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        created_at: datetime,
    ) -> Session:
        event = SessionEvent.create(
            session_id=session.session_id,
            sequence=len(events),
            event_type=event_type,
            actor=actor,
            payload=payload,
            created_at=created_at,
        )
        events.append(event)
        return apply_event(session, event)
