from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_worker import SessionRecoveryError, SessionRecoveryService


def test_session_recovery_service_rebuilds_and_persists_projection(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "worker.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 30, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Recover Session"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": "Recover Session", "user_input": "continue"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        )
    )

    recovered = SessionRecoveryService(event_store, projection_store).recover_session(
        session_id
    )

    assert recovered.event_count == 3
    assert recovered.last_sequence == 2
    assert recovered.is_terminal is False
    assert recovered.session.status.value == "running"
    assert projection_store.get_session(session_id) == recovered.session


def test_session_recovery_service_marks_terminal_session(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 35, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Terminal Session"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": "Terminal Session", "user_input": "continue"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=created_at,
        )
    )

    recovered = SessionRecoveryService(event_store, projection_store).recover_session(
        session_id
    )

    assert recovered.is_terminal is True
    assert recovered.session.status.value == "completed"


def test_session_recovery_service_rejects_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)

    with pytest.raises(SessionRecoveryError, match="cannot recover missing session"):
        SessionRecoveryService(event_store, projection_store).recover_session(
            new_session_id()
        )


def test_session_recovery_service_resumes_from_projection_delta(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    event_store = SQLiteEventStore(database_path)
    projection_store = SQLiteProjectionStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 19, 23, 40, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Resume Delta"},
            created_at=created_at,
        )
    )
    task_prepared = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={"title": "Resume Delta", "user_input": "continue"},
        created_at=created_at,
    )
    event_store.append(task_prepared)
    stale_projection = rebuild_session(
        event_store.list_for_session(session_id)
    )
    projection_store.save_session(stale_projection)
    attempt_started = SessionEvent.create(
        session_id=session_id,
        sequence=2,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
        created_at=created_at,
    )
    event_store.append(attempt_started)
    completed = SessionEvent.create(
        session_id=session_id,
        sequence=3,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"summary": "done"},
        created_at=created_at,
    )
    event_store.append(completed)

    recovered = SessionRecoveryService(event_store, projection_store).recover_session(
        session_id
    )

    assert recovered.event_count == 4
    assert recovered.last_sequence == 3
    assert recovered.is_terminal is True
    assert recovered.session.status.value == "completed"
    assert projection_store.get_session(session_id) == recovered.session
