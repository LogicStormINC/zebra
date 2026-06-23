from datetime import UTC, datetime

import pytest
from agent_core.application import SessionMessageAppendCommand, SessionMessageAppendService
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.sessions import Session, SessionStatus


def test_session_message_append_service_builds_user_message_event() -> None:
    created_at = datetime(2026, 6, 23, 11, 0, tzinfo=UTC)
    session = Session.create(title="Append message", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.READY,
            "current_sequence": 2,
        }
    )

    event = SessionMessageAppendService().build_event(
        session=session,
        next_sequence=3,
        command=SessionMessageAppendCommand(
            content="Please continue from the latest state.",
            appended_at=created_at,
        ),
    )

    assert event.sequence == 3
    assert event.event_type is EventType.USER_MESSAGE_RECEIVED
    assert event.actor is EventActor.USER
    assert event.payload == {"content": "Please continue from the latest state."}


def test_session_message_append_service_rejects_terminal_session() -> None:
    session = Session.create(title="Terminal").model_copy(
        update={"status": SessionStatus.COMPLETED}
    )

    with pytest.raises(ValueError, match="cannot append a message to a terminal session"):
        SessionMessageAppendService().build_event(
            session=session,
            next_sequence=1,
            command=SessionMessageAppendCommand(content="Try again."),
        )
