from pathlib import Path

from agent_storage import SQLiteDeliveryAuditStore
from fastapi.testclient import TestClient
from pull_request_support import (
    _git_workspace,
    _seed_ready_session,
    _settings,
)
from zebra_agent_api import create_http_app
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_api_pull_request_rejects_policy_blocked_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="workspace_write")

    response = create_app(database_path).open_session_pull_request(
        str(session_id),
        {"title": "Add feature"},
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "policy_blocked",
        "reason": "pull request requires full_access session policy",
        "idempotency_key": None,
    }
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].status == "policy_blocked"
    assert audit_records[0].policy_profile == "workspace_write"

def test_api_pull_request_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").open_session_pull_request(
        "00000000-0000-0000-0000-000000000001",
        {"title": "Add feature"},
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
        "idempotency_key": None,
    }

def test_api_pull_request_rejects_invalid_session_id(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").open_session_pull_request(
        "not-a-valid-uuid",
        {"title": "Add feature"},
    )

    assert response.status_code == 400
    assert response.body == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }

def test_api_pull_request_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(database_path).open_session_pull_request(
        str(session_id),
        {"title": "   "},
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "title must be a non-blank string",
    }

def test_route_adapter_handles_session_pull_request(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/pull-request",
            body={"title": "Route PR"},
        )
    )

    assert response.status_code == 200
    assert response.body["pull_request"]["status"] == "dry_run"

def test_api_pull_request_replays_idempotent_response(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    app = create_app(database_path)
    payload = {"title": "Add feature", "base_branch": "main"}

    first_response = app.open_session_pull_request(
        str(session_id),
        payload,
        idempotency_key="pr-key-1",
    )
    replayed_response = app.open_session_pull_request(
        str(session_id),
        payload,
        idempotency_key="pr-key-1",
    )

    assert first_response.status_code == 200
    assert replayed_response.status_code == 200
    assert replayed_response.body == first_response.body
    assert replayed_response.body["idempotency_key"] == "pr-key-1"
    audit_records = SQLiteDeliveryAuditStore(database_path).list_for_session(session_id)
    assert len(audit_records) == 1
    assert audit_records[0].idempotency_key == "pr-key-1"

def test_api_pull_request_rejects_idempotency_key_reused_for_different_payload(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    app = create_app(database_path)

    app.open_session_pull_request(
        str(session_id),
        {"title": "Add feature", "base_branch": "main"},
        idempotency_key="pr-key-1",
    )
    response = app.open_session_pull_request(
        str(session_id),
        {"title": "Add feature", "base_branch": "develop"},
        idempotency_key="pr-key-1",
    )

    assert response.status_code == 409
    assert response.body == {
        "status": "idempotency_conflict",
        "reason": "idempotency key reused with different request",
    }

def test_route_adapter_forwards_pull_request_idempotency_key(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    adapter = RouteAdapter(create_app(database_path))
    request = RouteRequest(
        method="POST",
        path=f"/sessions/{session_id}/pull-request",
        body={"title": "Route PR"},
        headers={"idempotency-key": "route-pr-1"},
    )

    first_response = adapter.handle(request)
    replayed_response = adapter.handle(request)

    assert first_response.status_code == 200
    assert replayed_response.body == first_response.body
    assert replayed_response.body["idempotency_key"] == "route-pr-1"

def test_http_app_session_pull_request_requires_bearer_token_when_configured(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(
        f"/sessions/{session_id}/pull-request",
        json={"title": "Add feature"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }

def test_http_app_session_pull_request_rejects_invalid_session_id(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions/not-a-valid-uuid/pull-request",
        json={"title": "Add feature"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }
