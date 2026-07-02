from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventType
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_message_append_appends_user_message(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)

    result = execute(
        [
            "message",
            str(session_id),
            "--content",
            "Please continue from the last checkpoint.",
            "--database",
            str(database_path),
        ]
    )
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert result.command == "message"
    assert result.payload == {
        "session_id": str(session_id),
        "database": str(database_path),
        "appended": True,
        "content": "Please continue from the last checkpoint.",
        "sequence": 3,
        "status": "ready",
        "current_sequence": 3,
    }
    assert events[-1].event_type is EventType.USER_MESSAGE_RECEIVED
    assert events[-1].payload == {"content": "Please continue from the last checkpoint."}


def test_cli_message_append_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)

    result = execute(
        [
            "message",
            str(session_id),
            "--content",
            "   ",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "database": str(database_path),
        "status": "invalid_request",
        "reason": "content must be a non-blank string",
    }


def test_cli_message_append_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "message",
            "00000000-0000-0000-0000-000000000001",
            "--content",
            "Continue.",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "database": str(database_path),
        "status": "not_found",
    }


def test_cli_message_append_rejects_terminal_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Terminal message").model_copy(
            update={"status": SessionStatus.COMPLETED}
        )
    )

    result = execute(
        [
            "message",
            str(session.session_id),
            "--content",
            "Try again.",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": str(session.session_id),
        "database": str(database_path),
        "status": "not_appendable",
        "reason": "cannot_append_to_terminal_session",
    }


def _seed_ready_session(database_path: Path, *, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Append contract",
            user_input="Inspect and continue.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id
