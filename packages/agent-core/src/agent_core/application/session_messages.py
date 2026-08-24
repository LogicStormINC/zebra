from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.turns import derive_turn_id


@dataclass(frozen=True)
class SessionMessageAppendCommand:
    content: str
    clarification_id: str | None = None
    appended_at: datetime | None = None
    prior_human_turns: int = 0
    turn_id: str | None = None
    # Exactly-one-open-Turn invariant (ADR-026 §5): callers that can read
    # the event stream must report whether a Turn is still open.
    open_turn_exists: bool = False


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
        if session.status is SessionStatus.WAITING_INPUT:
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
        if session.status in {SessionStatus.RUNNING, SessionStatus.WAITING_APPROVAL}:
            # A turn is still executing: a second normal message must not
            # silently run concurrently inside the same turn (ADR-026 §5).
            raise ValueError("turn_in_progress")
        if command.open_turn_exists:
            # READY/SUSPENDED sessions can still hold an unexecuted Turn
            # (bootstrap Turn 0, a re-armed follow-up, a suspended turn);
            # a second normal message would create two open Turns.
            raise ValueError("turn_in_progress")
        turn_id = command.turn_id or str(
            derive_turn_id(session.session_id, command.prior_human_turns)
        )
        return SessionEvent.create(
            session_id=session.session_id,
            sequence=next_sequence,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={
                "content": content,
                "turn_id": turn_id,
                "turn_index": command.prior_human_turns,
                "origin": "human",
            },
            created_at=command.appended_at,
        )
