from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.sessions import Session
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_memory_lists_repo_scoped_records(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory",
            user_input="Inspect memories.",
            workspace_root=workspace.resolve(),
        )
    )
    for event in bootstrap.events:
        SQLiteEventStore(database_path).append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    record = _memory_record(str(workspace.resolve()), str(bootstrap.session.session_id))
    SQLiteMemoryStore(database_path).upsert(record)

    result = execute(
        ["memory", str(bootstrap.session.session_id), "--database", str(database_path)]
    )

    assert result.command == "memory"
    assert result.payload == {
        "session_id": str(bootstrap.session.session_id),
        "database": str(database_path),
        "status": "ok",
        "repo_id": str(workspace.resolve()),
        "memories": [record.model_dump(mode="json")],
    }


def test_cli_memory_reports_unavailable_without_workspace(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No workspace")
    )

    result = execute(["memory", str(session.session_id), "--database", str(database_path)])

    assert result.payload == {
        "session_id": str(session.session_id),
        "database": str(database_path),
        "status": "memory_unavailable",
        "reason": "session workspace_root is unavailable",
    }


def test_cli_memory_reports_missing_session(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"

    result = execute(
        [
            "memory",
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


def _memory_record(repo_id: str, source_session_id: str) -> MemoryRecord:
    created_at = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000112")),
        memory_type=MemoryType.PROCEDURE,
        text="rerun make check after memory wiring",
        confidence=0.9,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id=repo_id,
        source_session_id=SessionId(UUID(source_session_id)),
        created_at=created_at,
        updated_at=created_at,
    )
