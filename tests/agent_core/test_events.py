from datetime import UTC, datetime

import pytest
from agent_core.contracts import EventPayloadValidationError
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
            payload={"content": "continue"},
            created_at=datetime(2026, 6, 18, 12, 0, 0),
        )


def test_session_event_rejects_negative_sequence() -> None:
    with pytest.raises(ValidationError):
        SessionEvent.create(
            session_id=new_session_id(),
            sequence=-1,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "bootstrap"},
            created_at=datetime.now(UTC),
        )


def test_session_event_create_rejects_invalid_payload_for_covered_event() -> None:
    with pytest.raises(
        EventPayloadValidationError,
        match="invalid payload for session_created",
    ):
        SessionEvent.create(
            session_id=new_session_id(),
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"unexpected": True},
        )


def test_session_event_create_allows_unregistered_event_payload() -> None:
    event = SessionEvent.create(
        session_id=new_session_id(),
        sequence=1,
        event_type=EventType.PLAN_PROPOSED,
        actor=EventActor.HARNESS,
        payload={"summary": "draft plan", "metadata": {"step_count": 2}},
        created_at=datetime.now(UTC),
    )

    assert event.payload == {
        "summary": "draft plan",
        "metadata": {"step_count": 2},
    }


def test_model_response_delta_preserves_whitespace_and_rejects_empty_content() -> None:
    payload = {
        "attempt_number": 1,
        "model_call_id": "00000000-0000-0000-0000-000000000146",
        "delta_index": 0,
        "content_delta": " hello ",
    }

    event = SessionEvent.create(
        session_id=new_session_id(),
        sequence=1,
        event_type=EventType.MODEL_RESPONSE_DELTA,
        actor=EventActor.HARNESS,
        payload=payload,
    )

    assert event.payload == payload
    with pytest.raises(
        EventPayloadValidationError,
        match="invalid payload for model_response_delta",
    ):
        SessionEvent.create(
            session_id=new_session_id(),
            sequence=1,
            event_type=EventType.MODEL_RESPONSE_DELTA,
            actor=EventActor.HARNESS,
            payload={**payload, "content_delta": ""},
        )
