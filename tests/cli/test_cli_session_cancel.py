from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.workspaces import WorkspaceStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_cancel_command_marks_session_cancelled(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)

    result = execute(["cancel", str(session_id), "--database", str(database_path)])

    updated_session = SQLiteProjectionStore(database_path).get_session(session_id)
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert result.command == "cancel"
    assert result.payload == {
        "session_id": str(session_id),
        "database": str(database_path),
        "cancelled": True,
        "status": "cancelled",
        "workspace_status": "cancelled",
    }
    assert updated_session is not None
    assert updated_session.status is SessionStatus.CANCELLED
    assert workspace is not None
    assert workspace.status is WorkspaceStatus.CANCELLED
    assert events[-1].event_type is EventType.SESSION_CANCELLED


def test_cli_cancel_command_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "cancel",
            "00000000-0000-0000-0000-000000000001",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
    }


def test_cli_cancel_command_rejects_terminal_session(tmp_path: Path) -> None:
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

    result = execute(["cancel", str(session_id), "--database", str(database_path)])

    assert result.payload == {
        "session_id": str(session_id),
        "database": str(database_path),
        "status": "not_cancellable",
        "reason": "session_cannot_be_cancelled_from_its_current_state",
    }


def _seed_ready_session(database_path: Path, *, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cancel contract",
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
