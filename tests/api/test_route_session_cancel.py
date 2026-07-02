from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.workspaces import WorkspaceStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_route_adapter_handles_session_cancel(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/cancel",
            body={},
        )
    )

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session_id),
        "cancelled": True,
        "status": "cancelled",
        "workspace_status": "cancelled",
    }


def test_route_adapter_rejects_terminal_session_cancel(tmp_path: Path) -> None:
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
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/cancel",
            body={},
        )
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "not_cancellable",
        "reason": "session_cannot_be_cancelled_from_its_current_state",
    }


def _seed_ready_session(database_path: Path, *, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cancel route",
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
