from pathlib import Path

from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_route_adapter_handles_approval_grant(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session.session_id}/approve",
            body={"operator": "alice", "reason": "safe"},
        )
    )

    assert response.status_code == 200
    assert response.body["approval_id"] == str(session.session_id)
    assert response.body["decision"] == "approve"
    assert response.body["status"] == "running"


def test_route_adapter_handles_approval_reject(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session.session_id}/reject",
            body={},
        )
    )

    assert response.status_code == 200
    assert response.body["approval_id"] == str(session.session_id)
    assert response.body["decision"] == "reject"
    assert response.body["status"] == "failed"


def test_route_adapter_rejects_invalid_approval_state(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No approval needed")
    )
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session.session_id}/approve",
            body={},
        )
    )

    assert response.status_code == 409
    assert response.body["status"] == "invalid_state"


def test_route_adapter_rejects_invalid_approval_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session.session_id}/reject",
            body={"operator": "   "},
        )
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "operator must be a non-blank string when provided",
    }


def _seed_waiting_session(database_path: Path) -> Session:
    session = Session.create(title="Waiting approval").model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 2,
        }
    )
    return SQLiteProjectionStore(database_path).save_session(session)
