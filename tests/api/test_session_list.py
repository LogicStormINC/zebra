from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    sqlite_control_plane_stores,
)
from fastapi.testclient import TestClient
from zebra_agent_api import RouteAdapter, RouteRequest, create_app, create_http_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


@pytest.mark.parametrize("path", ["/sessions", "/tasks"])
def test_queued_creation_prepares_task_before_cold_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    from uuid import UUID

    from tests.api.test_tenant_isolation import TENANT_A, TENANT_B

    database_path = tmp_path / "sessions.sqlite"
    created = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path=path,
            body={"prompt": "Cold queued task", "workspace": str(tmp_path), "execute": False},
            host_context=TENANT_A,
        )
    )
    assert created.status_code == 201
    task_id = str(created.body["session_id"])
    cold_stores = sqlite_control_plane_stores(database_path)
    task = cold_stores.tasks.get_task(TaskId(UUID(task_id)))
    assert task is not None
    assert task.active_segment_id == SessionId(UUID(task_id))
    assert task.current_sequence == created.body["current_sequence"] == 2
    assert len(cold_stores.tasks.segments(task.task_id)) == 1
    page = cold_stores.tasks.read_event_page(task.task_id, -1)
    assert [item.task_sequence for item in page.events] == [0, 1, 2]

    def no_read_adoption(*args: object, **kwargs: object) -> None:
        pytest.fail("GET must not prepare a Task")

    monkeypatch.setattr(SQLiteAgentTaskStore, "ensure_for_session", no_read_adoption)
    cold = RouteAdapter(create_app(database_path, stores=cold_stores))
    own = cold.handle(RouteRequest("GET", f"/tasks/{task_id}", host_context=TENANT_A))
    other = cold.handle(RouteRequest("GET", f"/tasks/{task_id}", host_context=TENANT_B))
    own_list = cold.handle(RouteRequest("GET", "/sessions", host_context=TENANT_A))
    other_list = cold.handle(RouteRequest("GET", "/sessions", host_context=TENANT_B))
    assert own.status_code == 200 and own.body["task_id"] == task_id
    assert other.status_code == 404
    assert [item["session_id"] for item in own_list.body["sessions"]] == [task_id]
    assert other_list.body["sessions"] == []


def test_queued_creation_cannot_report_success_when_task_preparation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Task preparation unavailable")

    monkeypatch.setattr(SQLiteAgentTaskStore, "ensure_for_session", unavailable)
    with pytest.raises(RuntimeError, match="Task preparation unavailable"):
        create_app(tmp_path / "sessions.sqlite").create_session({"prompt": "Queued task"})


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
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite", settings=_settings("secret")))

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
    SQLiteAgentTaskStore(database_path).ensure_for_session(session.session_id)
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
