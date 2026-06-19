from dataclasses import dataclass, field
from datetime import datetime

from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports.clock import ClockPort


@dataclass
class HarnessEventRecorder:
    session: Session
    clock: ClockPort
    events: list[SessionEvent] = field(default_factory=list)

    def record(
        self,
        *,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        created_at: datetime | None = None,
    ) -> SessionEvent:
        event = SessionEvent.create(
            session_id=self.session.session_id,
            sequence=len(self.events),
            event_type=event_type,
            actor=actor,
            payload=payload,
            created_at=created_at or self.clock.now(),
        )
        self.events.append(event)
        self.session = apply_event(self.session, event)
        return event

    def record_draft(
        self,
        draft: HarnessEventDraft,
        *,
        created_at: datetime | None = None,
    ) -> SessionEvent:
        return self.record(
            event_type=draft.event_type,
            actor=draft.actor,
            payload=draft.payload,
            created_at=created_at,
        )
