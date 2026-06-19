from datetime import UTC, datetime

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from pydantic import ValidationError


def test_session_event_create_sets_defaults() -> None:
    event = SessionEvent.create(
        session_id=new_session_id(),
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "bootstrap"},
    )

    assert event.event_type is EventType.SESSION_CREATED
    assert event.actor is EventActor.SYSTEM
    assert event.payload["title"] == "bootstrap"
    assert event.created_at.tzinfo is not None


def test_session_event_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        SessionEvent.create(
            session_id=new_session_id(),
            sequence=1,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            created_at=datetime(2026, 6, 18, 12, 0, 0),
        )


def test_session_event_rejects_negative_sequence() -> None:
    with pytest.raises(ValidationError):
        SessionEvent.create(
            session_id=new_session_id(),
            sequence=-1,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            created_at=datetime.now(UTC),
        )
