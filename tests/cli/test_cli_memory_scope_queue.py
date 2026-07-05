from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_memory_queue_lists_only_candidate_repo_records(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_session(database_path, workspace)
    _append_doc_source_event(database_path, session_id)
    candidate = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000181",
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
        memory_type=MemoryType.PROCEDURE,
        text="Run make check after worker changes.",
        status=MemoryStatus.CANDIDATE,
    )
    confirmed = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000182",
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
        memory_type=MemoryType.PROCEDURE,
        text="Old confirmed rule.",
        status=MemoryStatus.CONFIRMED,
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(candidate)
    store.upsert(confirmed)

    result = execute(["memory-queue", str(session_id), "--database", str(database_path)])

    assert result.command == "memory-queue"
    assert result.payload["repo_id"] == str(workspace.resolve())
    assert [memory["memory_id"] for memory in result.payload["memories"]] == [
        str(candidate.memory_id)
    ]


def test_cli_memory_user_queue_reads_inventory(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_session(database_path, workspace)
    _append_user_source_event(database_path, session_id)
    candidate = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000183",
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        source_session_id=session_id,
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
        status=MemoryStatus.CANDIDATE,
    )
    expired = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000184",
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        source_session_id=session_id,
        memory_type=MemoryType.PREFERENCE,
        text="Old preference.",
        status=MemoryStatus.EXPIRED,
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(candidate)
    store.upsert(expired)

    result = execute(["memory-user-queue", "user-1", "--database", str(database_path)])

    assert result.command == "memory-user-queue"
    assert result.payload["user_id"] == "user-1"
    assert result.payload["memories"][0]["source"]["kind"] == "user_message"
    assert [memory["memory_id"] for memory in result.payload["memories"]] == [
        str(candidate.memory_id)
    ]


def test_cli_memory_tenant_queue_reads_inventory(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_session(database_path, workspace)
    _append_doc_source_event(database_path, session_id)
    candidate = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000185",
        visibility=MemoryVisibility.TENANT,
        tenant_id="tenant-1",
        source_session_id=session_id,
        memory_type=MemoryType.PROJECT_RULE,
        text="Use the repo default commands: `make sync`, `make check`.",
        status=MemoryStatus.CANDIDATE,
    )
    expired = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000186",
        visibility=MemoryVisibility.TENANT,
        tenant_id="tenant-1",
        source_session_id=session_id,
        memory_type=MemoryType.PROJECT_RULE,
        text="Old rule.",
        status=MemoryStatus.EXPIRED,
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(candidate)
    store.upsert(expired)

    result = execute(["memory-tenant-queue", "tenant-1", "--database", str(database_path)])

    assert result.command == "memory-tenant-queue"
    assert result.payload["tenant_id"] == "tenant-1"
    assert result.payload["memories"][0]["source"]["locator"] == "AGENTS.md"
    assert [memory["memory_id"] for memory in result.payload["memories"]] == [
        str(candidate.memory_id)
    ]


def _seed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory scope queue",
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
    repo_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
) -> MemoryRecord:
    created_at = datetime(2026, 7, 4, 9, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.9,
        status=status,
        visibility=visibility,
        repo_id=repo_id,
        user_id=user_id,
        tenant_id=tenant_id,
        source_session_id=source_session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )


def _append_user_source_event(database_path: Path, session_id: SessionId) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": "Preference: Prefer concise CLI output."},
            created_at=datetime(2026, 7, 4, 9, 0, tzinfo=UTC),
        )
    )


def _append_doc_source_event(database_path: Path, session_id: SessionId) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "attempt_number": 1,
                "tool_name": "files.read",
                "status": "executed",
                "output": "# Zebra Agent Repository Rules",
                "metadata": {
                    "path": "AGENTS.md",
                    "byte_count": 32,
                    "truncated": False,
                },
            },
            created_at=datetime(2026, 7, 4, 9, 0, tzinfo=UTC),
        )
    )
