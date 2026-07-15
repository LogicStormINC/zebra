from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session


@dataclass(frozen=True)
class SessionMessageAppendCommand:
    content: str
    clarification_id: str | None = None
    appended_at: datetime | None = None


class SessionMessageAppendService:
    def build_event(
        self,
        *,
        session: Session,
        next_sequence: int,
        command: SessionMessageAppendCommand,
    ) -> SessionEvent:
        content = command.content.strip()
        if not content:
            raise ValueError("content_must_not_be_blank")
        if session.status.value in {"completed", "failed", "cancelled"}:
            raise ValueError("cannot append a message to a terminal session")
        if session.status.value == "waiting_input":
            clarification = session.clarification_context
            if clarification is None:
                raise ValueError("clarification_context_missing")
            if command.clarification_id is None:
                raise ValueError("clarification_id_required")
            if command.clarification_id != clarification.clarification_id:
                raise ValueError("clarification_id_mismatch")
            return SessionEvent.create(
                session_id=session.session_id,
                sequence=next_sequence,
                event_type=EventType.CLARIFICATION_RESPONDED,
                actor=EventActor.USER,
                payload={
                    "clarification_id": clarification.clarification_id,
                    "content": content,
                    "selected_choice": any(
                        content.casefold() == choice.casefold() for choice in clarification.choices
                    ),
                },
                created_at=command.appended_at,
            )
        if command.clarification_id is not None:
            raise ValueError("no_active_clarification")
        return SessionEvent.create(
            session_id=session.session_id,
            sequence=next_sequence,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": content},
            created_at=command.appended_at,
        )
