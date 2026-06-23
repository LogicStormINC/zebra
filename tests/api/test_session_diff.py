from pathlib import Path
from subprocess import run

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_api_get_session_diff_reports_dirty_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace)

    response = create_app(database_path).get_session_diff(str(session_id))

    assert response.status_code == 200
    assert response.body["session_id"] == str(session_id)
    assert response.body["workspace"] == str(workspace)
    assert response.body["clean"] is False
    assert response.body["git_status"] == " M tracked.txt\n"
    assert "+changed" in str(response.body["diff"])


def test_api_get_session_diff_reports_clean_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace)

    response = create_app(database_path).get_session_diff(str(session_id))

    assert response.status_code == 200
    assert response.body["clean"] is True
    assert response.body["git_status"] == ""
    assert response.body["diff"] == ""


def test_api_get_session_diff_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session_diff(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_api_get_session_diff_rejects_non_git_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "not-git"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)

    response = create_app(database_path).get_session_diff(str(session_id))

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "diff_unavailable",
        "reason": "workspace_root is not a git repository",
    }


def test_route_adapter_handles_session_diff(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("route change\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(RouteRequest(method="GET", path=f"/sessions/{session_id}/diff"))

    assert response.status_code == 200
    assert response.body["clean"] is False
    assert "+route change" in str(response.body["diff"])


def test_http_app_session_diff_requires_bearer_token_when_configured(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(f"/sessions/{session_id}/diff")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Diff session",
            user_input="Review the diff.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _git_workspace(path: Path) -> Path:
    path.mkdir()
    run(("git", "init"), cwd=path, check=True, capture_output=True, text=True)
    run(
        ("git", "config", "user.name", "Zebra Agent"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    run(
        ("git", "config", "user.email", "zebra@example.com"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    run(("git", "add", "tracked.txt"), cwd=path, check=True, capture_output=True, text=True)
    run(("git", "commit", "-m", "init"), cwd=path, check=True, capture_output=True, text=True)
    return path.resolve()


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
