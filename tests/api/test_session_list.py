from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import RouteAdapter, RouteRequest, create_app, create_http_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_route_lists_recent_sessions_with_durable_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    older = _seed_session(database_path, "Older", minute=1, workspace_root=tmp_path / "older")
    newest = _seed_session(
        database_path,
        "Newest",
        minute=2,
        workspace_root=tmp_path / "newest",
        policy_profile="full_access",
        status=SessionStatus.COMPLETED,
    )

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(method="GET", path="/sessions", query={"limit": "1"})
    )

    assert response.status_code == 200
    assert response.body["count"] == 1
    assert response.body["limit"] == 1
    assert response.body["sessions"] == [
        {
            "session_id": str(newest.session_id),
            "title": "Newest",
            "status": "completed",
            "task_status": "completed",
            "current_sequence": 0,
            "created_at": newest.created_at.isoformat(),
            "updated_at": newest.updated_at.isoformat(),
            "workspace": {
                "workspace_root": str((tmp_path / "newest").resolve()),
                "tool_profile": "coding",
                "network_profile": "none",
                "network_allowlist": [],
                "status": "prepared",
                "current_sequence": 0,
                "prepared_at": newest.created_at.isoformat(),
                "updated_at": newest.updated_at.isoformat(),
                "policy_profile": "full_access",
                "last_attempt_number": 0,
            },
        }
    ]
    assert str(older.session_id) not in str(response.body)


def test_http_session_list_validates_limit(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/sessions?limit=101")

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "limit must be an integer between 1 and 100",
    }


def test_http_session_list_requires_configured_bearer_token(tmp_path: Path) -> None:
    client = TestClient(
        create_http_app(tmp_path / "sessions.sqlite", settings=_settings("secret"))
    )

    unauthorized = client.get("/sessions")
    authorized = client.get(
        "/sessions",
        headers={"Authorization": "Bearer secret"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json() == {"sessions": [], "count": 0, "limit": 50}


def _seed_session(
    database_path: Path,
    title: str,
    *,
    minute: int,
    workspace_root: Path,
    policy_profile: str = "workspace_write",
    status: SessionStatus = SessionStatus.READY,
) -> Session:
    timestamp = datetime(2026, 7, 14, 2, minute, tzinfo=UTC)
    session = Session.create(title=title, created_at=timestamp).model_copy(
        update={"status": status, "updated_at": timestamp}
    )
    SQLiteProjectionStore(database_path).save_session(session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        WorkspaceProjection(
            session_id=session.session_id,
            workspace_root=str(workspace_root.resolve()),
            prepared_at=timestamp,
            updated_at=timestamp,
            current_sequence=0,
            status=WorkspaceStatus.PREPARED,
            policy_profile=policy_profile,
            last_attempt_number=0,
        )
    )
    return session


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
