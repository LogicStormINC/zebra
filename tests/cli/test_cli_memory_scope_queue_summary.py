from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_memory_queue_summary_reports_pending_counts(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_session(database_path, workspace)
    first = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000241",
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
        memory_type=MemoryType.PROCEDURE,
        text="Run make check after worker changes.",
        status=MemoryStatus.CANDIDATE,
        updated_at=datetime(2026, 7, 6, 9, 0, tzinfo=UTC),
    )
    latest = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000242",
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
        memory_type=MemoryType.PROCEDURE,
        text="Refresh queue summary docs.",
        status=MemoryStatus.CANDIDATE,
        updated_at=datetime(2026, 7, 6, 10, 0, tzinfo=UTC),
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(first)
    store.upsert(latest)

    result = execute(["memory-queue-summary", str(session_id), "--database", str(database_path)])

    assert result.command == "memory-queue-summary"
    assert result.payload["session_id"] == str(session_id)
    assert result.payload["pending_count"] == 2
    assert result.payload["queue_status"] == "pending"
    assert result.payload["latest_memory_id"] == str(latest.memory_id)


def test_cli_memory_user_queue_summary_reports_empty_queue(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"

    result = execute(["memory-user-queue-summary", "user-1", "--database", str(database_path)])

    assert result.command == "memory-user-queue-summary"
    assert result.payload == {
        "database": str(database_path),
        "status": "ok",
        "user_id": "user-1",
        "pending_count": 0,
        "queue_status": "empty",
        "latest_memory_id": None,
        "latest_updated_at": None,
    }


def _seed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory scope queue summary",
            user_input="Inspect memories.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _memory_record(
    *,
    memory_id: str,
    visibility: MemoryVisibility,
    source_session_id: SessionId,
    memory_type: MemoryType,
    text: str,
    status: MemoryStatus,
    updated_at: datetime,
    repo_id: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.9,
        status=status,
        visibility=visibility,
        repo_id=repo_id,
        source_session_id=source_session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=updated_at,
        updated_at=updated_at,
    )
