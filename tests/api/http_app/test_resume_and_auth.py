from pathlib import Path

import zebra_agent_worker.execution as worker_execution_module
from agent_core.domain.sessions import Session
from agent_storage import SQLiteProjectionStore
from fastapi.testclient import TestClient
from http_app_support import (
    _fake_resume_gateway,
    _seed_ready_session,
    _settings,
)
from zebra_agent_api import create_http_app


def test_http_app_resume_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(f"/sessions/{session_id}/resume", json={})

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }

def test_http_app_suspend_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(f"/sessions/{session_id}/suspend", json={})

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }

def test_http_app_suspend_rejects_invalid_session_id(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post("/sessions/not-a-valid-uuid/suspend", json={})

    assert response.status_code == 400
    assert response.json() == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }

def test_http_app_resume_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(
        f"/sessions/{session_id}/resume",
        json={"lease_ttl_seconds": 0},
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "lease_ttl_seconds must be greater than zero",
    }

def test_http_app_resume_missing_session_returns_not_found(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions/00000000-0000-0000-0000-000000000001/resume",
        json={},
    )

    assert response.status_code == 404
    assert response.json() == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }

def test_http_app_resume_rejects_invalid_session_id(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions/not-a-valid-uuid/resume",
        json={},
    )

    assert response.status_code == 400
    assert response.json() == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }

def test_http_app_resume_terminal_session_returns_conflict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", _fake_resume_gateway)
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    first = client.post(f"/sessions/{session_id}/resume", json={})
    second = client.post(f"/sessions/{session_id}/resume", json={})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {
        "session_id": session_id,
        "status": "not_resumable",
        "reason": "cannot_resume_terminal_session",
    }

def test_http_app_rejects_invalid_json_body(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions",
        content="{invalid",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "request body must be valid JSON",
    }

def test_http_app_health_remains_public_with_auth_enabled(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite", settings=_settings("secret")))

    response = client.get("/health")

    assert response.status_code == 200

def test_http_app_session_routes_require_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Auth session")
    )
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(f"/sessions/{session.session_id}")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }

def test_http_app_session_routes_reject_invalid_bearer_token(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Auth session")
    )
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(
        f"/sessions/{session.session_id}",
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }

def test_http_app_session_routes_allow_valid_bearer_token(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Auth session")
    )
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(
        f"/sessions/{session.session_id}",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == str(session.session_id)

def test_http_app_stream_route_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Auth stream")
    )
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(f"/sessions/{session.session_id}/stream")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }
