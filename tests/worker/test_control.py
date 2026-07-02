from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.workspaces import WorkspaceStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_worker import SessionControlService


def test_session_control_service_cancels_ready_session(tmp_path: Path) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)

    result = SessionControlService(database_path).cancel_session(session_id)

    updated_session = SQLiteProjectionStore(database_path).get_session(session_id)
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert result.event.event_type is EventType.SESSION_CANCELLED
    assert updated_session is not None
    assert updated_session.status is SessionStatus.CANCELLED
    assert workspace is not None
    assert workspace.status is WorkspaceStatus.CANCELLED
    assert events[-1].event_type is EventType.SESSION_CANCELLED


def _seed_ready_session(database_path: Path, *, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Worker cancel",
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
