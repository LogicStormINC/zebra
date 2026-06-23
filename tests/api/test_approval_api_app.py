from pathlib import Path

from agent_core.domain.events import EventType
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app


def test_api_approve_records_granted_decision(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)

    response = create_app(database_path).approve(
        str(session.session_id),
        {"operator": "alice", "reason": "safe to continue"},
    )

    events = SQLiteEventStore(database_path).list_for_session(session.session_id)
    updated = SQLiteProjectionStore(database_path).get_session(session.session_id)

    assert response.status_code == 200
    assert response.body == {
        "approval_id": str(session.session_id),
        "session_id": str(session.session_id),
        "decision": "approve",
        "event_type": EventType.APPROVAL_GRANTED.value,
        "sequence": 3,
        "status": SessionStatus.RUNNING.value,
    }
    assert len(events) == 1
    assert events[0].event_type is EventType.APPROVAL_GRANTED
    assert updated is not None
    assert updated.status is SessionStatus.RUNNING


def test_api_reject_records_rejected_decision(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)

    response = create_app(database_path).reject(str(session.session_id), {})

    events = SQLiteEventStore(database_path).list_for_session(session.session_id)
    updated = SQLiteProjectionStore(database_path).get_session(session.session_id)

    assert response.status_code == 200
    assert response.body["decision"] == "reject"
    assert response.body["event_type"] == EventType.APPROVAL_REJECTED.value
    assert events[0].payload == {
        "operator": "api-operator",
        "reason": "reject via API",
    }
    assert updated is not None
    assert updated.status is SessionStatus.FAILED


def test_api_approval_returns_invalid_state_for_non_waiting_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No approval needed")
    )

    response = create_app(database_path).approve(str(session.session_id), {})

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "invalid_state",
        "reason": "approval decisions require a waiting approval session",
    }


def test_api_approval_returns_not_found_for_missing_session(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").reject(
        "00000000-0000-0000-0000-000000000001",
        {},
    )

    assert response.status_code == 404
    assert response.body == {
        "approval_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def _seed_waiting_session(database_path: Path) -> Session:
    session = Session.create(title="Waiting approval").model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 2,
        }
    )
    return SQLiteProjectionStore(database_path).save_session(session)
