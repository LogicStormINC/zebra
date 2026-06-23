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


def test_api_commit_session_creates_local_commit(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(database_path).commit_session(
        str(session_id),
        {
            "message": "Commit session changes",
            "author_name": "Zebra Agent",
            "author_email": "zebra@example.com",
        },
    )

    assert response.status_code == 201
    assert response.body["session_id"] == str(session_id)
    assert response.body["committed"] is True
    assert response.body["message"] == "Commit session changes"
    assert response.body["workspace"] == str(workspace)
    assert response.body["policy_profile"] == "full_access"
    assert len(str(response.body["commit_sha"])) == 40
    assert _git(workspace, ("git", "status", "--short")) == ""


def test_api_commit_session_rejects_policy_blocked_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="workspace_write")

    response = create_app(database_path).commit_session(
        str(session_id),
        {"message": "Try commit"},
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "policy_blocked",
        "reason": "commit requires full_access session policy",
    }


def test_api_commit_session_rejects_clean_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(database_path).commit_session(
        str(session_id),
        {"message": "No changes"},
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "commit_unavailable",
        "reason": "workspace has no changes to commit",
    }


def test_api_commit_session_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").commit_session(
        "00000000-0000-0000-0000-000000000001",
        {"message": "Commit"},
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_api_commit_session_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")

    response = create_app(database_path).commit_session(
        str(session_id),
        {"message": "   "},
    )

    assert response.status_code == 400
    assert response.body == {
        "status": "invalid_request",
        "reason": "message must be a non-blank string",
    }


def test_route_adapter_handles_session_commit(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    (workspace / "tracked.txt").write_text("route change\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/commit",
            body={"message": "Route commit"},
        )
    )

    assert response.status_code == 201
    assert response.body["committed"] is True


def test_http_app_session_commit_requires_bearer_token_when_configured(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = _git_workspace(tmp_path / "workspace")
    session_id = _seed_ready_session(database_path, workspace, policy_profile="full_access")
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(f"/sessions/{session_id}/commit", json={"message": "Commit"})

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def _seed_ready_session(
    database_path: Path,
    workspace_root: Path,
    *,
    policy_profile: str,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Commit session",
            user_input="Commit reviewed changes.",
            workspace_root=workspace_root.resolve(),
            policy_profile=policy_profile,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _git_workspace(path: Path) -> Path:
    path.mkdir()
    _git(path, ("git", "init"))
    _git(path, ("git", "config", "user.name", "Zebra Agent"))
    _git(path, ("git", "config", "user.email", "zebra@example.com"))
    (path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(path, ("git", "add", "tracked.txt"))
    _git(path, ("git", "commit", "-m", "init"))
    return path.resolve()


def _git(path: Path, command: tuple[str, ...]) -> str:
    return run(command, cwd=path, check=True, capture_output=True, text=True).stdout


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
