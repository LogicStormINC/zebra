from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session


@dataclass(frozen=True)
class SessionMessageAppendCommand:
    content: str
    appended_at: datetime | None = None


class SessionMessageAppendService:
    def build_event(
        self,
        *,
        session: Session,
        next_sequence: int,
        command: SessionMessageAppendCommand,
    ) -> SessionEvent:
        if session.status.value in {"completed", "failed", "cancelled"}:
            raise ValueError("cannot append a message to a terminal session")
        return SessionEvent.create(
            session_id=session.session_id,
            sequence=next_sequence,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": command.content},
            created_at=command.appended_at,
        )
