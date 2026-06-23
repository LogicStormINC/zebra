from pathlib import Path

from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_http_app_approves_waiting_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(
        f"/approvals/{session.session_id}/approve",
        json={"operator": "alice", "reason": "safe"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "approval_id": str(session.session_id),
        "session_id": str(session.session_id),
        "decision": "approve",
        "event_type": "approval_granted",
        "sequence": 3,
        "status": "running",
    }


def test_http_app_rejects_waiting_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(f"/approvals/{session.session_id}/reject", json={})

    assert response.status_code == 200
    assert response.json() == {
        "approval_id": str(session.session_id),
        "session_id": str(session.session_id),
        "decision": "reject",
        "event_type": "approval_rejected",
        "sequence": 3,
        "status": "failed",
    }


def test_http_app_approval_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(f"/approvals/{session.session_id}/approve", json={})

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def test_http_app_approval_rejects_invalid_state(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No approval needed")
    )
    client = TestClient(create_http_app(database_path))

    response = client.post(f"/approvals/{session.session_id}/approve", json={})

    assert response.status_code == 409
    assert response.json() == {
        "session_id": str(session.session_id),
        "status": "invalid_state",
        "reason": "approval decisions require a waiting approval session",
    }


def test_http_app_approval_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = _seed_waiting_session(database_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(
        f"/approvals/{session.session_id}/reject",
        json={"reason": "   "},
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "reason must be a non-blank string when provided",
    }


def _settings(auth_token: str | None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


def _seed_waiting_session(database_path: Path) -> Session:
    session = Session.create(title="Waiting approval").model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 2,
        }
    )
    return SQLiteProjectionStore(database_path).save_session(session)
