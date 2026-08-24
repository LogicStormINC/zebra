"""Durable message-Event construction with ADR-026 Turn identity."""

from agent_core.application import (
    SessionMessageAppendCommand,
    SessionMessageAppendService,
    current_turn,
    project_turns,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.sessions import Session
from agent_core.ports import EventStorePort


def build_session_message_event(
    *,
    event_store: EventStorePort,
    session: Session,
    content: str,
    clarification_id: str | None,
) -> SessionEvent:
    """Build the next durable message Event with ADR-026 Turn identity."""


    events = event_store.list_for_session(session.session_id)
    return SessionMessageAppendService().build_event(
        session=session,
        next_sequence=session.current_sequence + 1,
        command=SessionMessageAppendCommand(
            content=content,
            clarification_id=clarification_id,
            prior_human_turns=len(project_turns(events)),
            open_turn_exists=current_turn(events) is not None,
        ),
    )
