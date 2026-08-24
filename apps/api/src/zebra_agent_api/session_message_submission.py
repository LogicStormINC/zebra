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

from zebra_agent_api.responses import ApiResponse, conflict


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


def append_session_message_event(
    event_store: EventStorePort, event: SessionEvent
) -> SessionEvent | None:
    """Append a message event; None means a concurrent append won the race.

    Two concurrent appends can build the same next sequence: the loser
    reports a typed 409 sequence_conflict instead of a raw 500.
    """

    from agent_storage.event_rows import (  # noqa: PLC0415
        SessionEventIdempotencyConflictError,
    )

    try:
        return event_store.append(event)
    except (
        SessionEventIdempotencyConflictError,
        ValueError,
    ) as exc:
        if isinstance(exc, ValueError) and (
            "duplicate or conflicting session event" not in str(exc)
        ):
            raise
        return None


def message_sequence_conflict(session_id: str) -> ApiResponse:
    """Typed 409 for an append that lost the next-sequence race."""

    return conflict(
        session_id=session_id,
        status="sequence_conflict",
        reason="concurrent_append_won_the_sequence",
    )
