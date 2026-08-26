from datetime import UTC, datetime

import pytest
from agent_core.application import SessionMessageAppendCommand, SessionMessageAppendService
from agent_core.domain.clarifications import ClarificationContext
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
    assert event.payload["content"] == "Please continue from the latest state."
    assert event.payload["origin"] == "human"
    assert event.payload["turn_index"] == 0
    assert event.payload["turn_id"]


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


def test_session_message_append_resolves_only_matching_clarification() -> None:
    created_at = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    clarification_id = "00000000-0000-0000-0000-000000000124"
    session = Session.create(title="Clarify", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.WAITING_INPUT,
            "clarification_context": ClarificationContext(
                clarification_id=clarification_id,
                tool_call_id=clarification_id,
                question="Which audience should I prioritize?",
                choices=("Operators", "Analysts"),
                assistant_message="I need one decision.",
                requested_at=created_at,
            ),
        }
    )

    with pytest.raises(ValueError, match="clarification_id_required"):
        SessionMessageAppendService().build_event(
            session=session,
            next_sequence=1,
            command=SessionMessageAppendCommand(content="Operators"),
        )
    event = SessionMessageAppendService().build_event(
        session=session,
        next_sequence=1,
        command=SessionMessageAppendCommand(
            content="Operators",
            clarification_id=clarification_id,
            appended_at=created_at,
        ),
    )

    assert event.event_type is EventType.CLARIFICATION_RESPONDED
    assert event.payload == {
        "clarification_id": clarification_id,
        "content": "Operators",
        "selected_choice": True,
    }
