from datetime import UTC, datetime, timedelta

import pytest
from agent_core.application.session_projection import SessionProjectionError, rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.sessions import SessionStatus


def test_rebuild_session_applies_status_transitions() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "bootstrap"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            created_at=created_at + timedelta(seconds=1),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.MODEL_REQUEST_STARTED,
            actor=EventActor.HARNESS,
            created_at=created_at + timedelta(seconds=2),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.SYSTEM,
            created_at=created_at + timedelta(seconds=3),
        ),
    ]

    session = rebuild_session(events)

    assert session.title == "bootstrap"
    assert session.status is SessionStatus.COMPLETED
    assert session.current_sequence == 3
    assert session.updated_at == created_at + timedelta(seconds=3)


def test_rebuild_session_requires_session_created_first() -> None:
    with pytest.raises(SessionProjectionError, match="first event must be session_created"):
        rebuild_session(
            [
                SessionEvent.create(
                    session_id=new_session_id(),
                    sequence=0,
                    event_type=EventType.TASK_PREPARED,
                    actor=EventActor.HARNESS,
                    created_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
                )
            ]
        )


def test_rebuild_session_rejects_non_contiguous_sequences() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)

    with pytest.raises(SessionProjectionError, match="expected event sequence 1, got 2"):
        rebuild_session(
            [
                SessionEvent.create(
                    session_id=session_id,
                    sequence=0,
                    event_type=EventType.SESSION_CREATED,
                    actor=EventActor.SYSTEM,
                    payload={"title": "bootstrap"},
                    created_at=created_at,
                ),
                SessionEvent.create(
                    session_id=session_id,
                    sequence=2,
                    event_type=EventType.TASK_PREPARED,
                    actor=EventActor.HARNESS,
                    created_at=created_at + timedelta(seconds=1),
                ),
            ]
        )


def test_rebuild_session_requires_title_in_created_event() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)

    with pytest.raises(SessionProjectionError, match="must include a title"):
        rebuild_session(
            [
                SessionEvent.create(
                    session_id=session_id,
                    sequence=0,
                    event_type=EventType.SESSION_CREATED,
                    actor=EventActor.SYSTEM,
                    payload={},
                    created_at=created_at,
                )
            ]
        )
