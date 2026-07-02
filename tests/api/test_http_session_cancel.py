from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.workspaces import WorkspaceStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app


def test_http_app_cancels_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(f"/sessions/{session_id}/cancel", json={})

    assert response.status_code == 200
    assert response.json() == {
        "session_id": str(session_id),
        "cancelled": True,
        "status": "cancelled",
        "workspace_status": "cancelled",
    }


def test_http_app_cancel_missing_session_returns_not_found(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post("/sessions/00000000-0000-0000-0000-000000000001/cancel", json={})

    assert response.status_code == 404
    assert response.json() == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_http_app_cancel_terminal_session_returns_conflict(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    projection_store = SQLiteProjectionStore(database_path)
    session = projection_store.get_session(session_id)
    assert session is not None
    projection_store.save_session(session.model_copy(update={"status": SessionStatus.COMPLETED}))
    workspace_store = SQLiteWorkspaceProjectionStore(database_path)
    workspace = workspace_store.get_workspace(session_id)
    assert workspace is not None
    workspace_store.save_workspace(
        workspace.model_copy(update={"status": WorkspaceStatus.COMPLETED})
    )
    client = TestClient(create_http_app(database_path))

    response = client.post(f"/sessions/{session_id}/cancel", json={})

    assert response.status_code == 409
    assert response.json() == {
        "session_id": str(session_id),
        "status": "not_cancellable",
        "reason": "session_cannot_be_cancelled_from_its_current_state",
    }


def test_http_app_cancel_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(
        f"/sessions/{session_id}/cancel",
        json={"unexpected": True},
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "cancel does not accept request fields yet",
    }


def _seed_ready_session(database_path: Path, *, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cancel HTTP",
            user_input="Inspect and continue.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(list(bootstrap.events))
    )
    return bootstrap.session.session_id
