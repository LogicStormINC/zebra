from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteEventStore


def test_sqlite_event_store_appends_and_lists_session_events(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 0, tzinfo=UTC)
    created_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Replay Task"},
        created_at=created_at,
    )
    user_event = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "continue"},
        created_at=created_at,
    )

    store.append(created_event)
    store.append(user_event)

    assert store.list_for_session(session_id) == [created_event, user_event]


def test_sqlite_event_store_rejects_duplicate_sequence_for_same_session(
    tmp_path: Path,
) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 5, tzinfo=UTC)
    first_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.SYSTEM,
        payload={"title": "Duplicate Task"},
        created_at=created_at,
    )
    conflicting_event = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "duplicate"},
        created_at=created_at,
    )

    store.append(first_event)

    with pytest.raises(ValueError, match="duplicate or conflicting session event"):
        store.append(conflicting_event)


def test_sqlite_event_store_supports_projection_rebuild(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "events.db")
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 10, tzinfo=UTC)
    store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Projection Task"},
            created_at=created_at,
        )
    )
    store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": "Projection Task", "user_input": "continue"},
            created_at=created_at,
        )
    )
    store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        )
    )
    store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=created_at,
        )
    )

    session = rebuild_session(store.list_for_session(session_id))

    assert session.session_id == session_id
    assert session.status.value == "completed"
    assert session.current_sequence == 3
