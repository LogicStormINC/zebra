from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_memory_bulk_review_reports_applied_skipped_and_invalid(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000211",
        session_id=session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Run make check after worker changes.",
    )
    SQLiteMemoryStore(database_path).upsert(candidate)

    result = execute(
        [
            "memory-bulk-review",
            str(session_id),
            str(candidate.memory_id),
            str(candidate.memory_id),
            "not-a-uuid",
            "00000000-0000-0000-0000-000000000299",
            "--decision",
            "confirm",
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "memory-bulk-review"
    assert result.payload["session_id"] == str(session_id)
    assert result.payload["applied_count"] == 1
    assert result.payload["skipped_count"] == 2
    assert result.payload["invalid_count"] == 1
    assert result.payload["results"][0]["memory_status"] == "confirmed"
    assert result.payload["results"][1]["status"] == "duplicate_request"
    assert result.payload["results"][2]["status"] == "invalid_id"
    assert result.payload["results"][3]["status"] == "not_found"


def test_cli_memory_tenant_bulk_review_expires_candidates(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000212",
        session_id=session_id,
        visibility=MemoryVisibility.TENANT,
        tenant_id="tenant-1",
        memory_type=MemoryType.PROJECT_RULE,
        text="Use the repo default commands: `make sync`, `make check`.",
    )
    SQLiteMemoryStore(database_path).upsert(candidate)

    result = execute(
        [
            "memory-tenant-bulk-review",
            "tenant-1",
            str(candidate.memory_id),
            "--decision",
            "expire",
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "memory-tenant-bulk-review"
    assert result.payload["tenant_id"] == "tenant-1"
    assert result.payload["applied_count"] == 1
    assert result.payload["results"][0]["memory_status"] == "expired"


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory scope bulk review",
            user_input="Inspect memories.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    completed = bootstrap.session.model_copy(
        update={
            "status": bootstrap.session.status.COMPLETED,
            "current_sequence": 3,
        }
    )
    event_store.append(
        SessionEvent.create(
            session_id=completed.session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"reason": "done"},
            created_at=datetime(2026, 7, 5, 9, 0, tzinfo=UTC),
        )
    )
    SQLiteProjectionStore(database_path).save_session(completed)
    return completed.session_id


def _candidate_record(
    *,
    memory_id: str,
    session_id: SessionId,
    visibility: MemoryVisibility,
    memory_type: MemoryType,
    text: str,
    repo_id: str | None = None,
    tenant_id: str | None = None,
) -> MemoryRecord:
    created_at = datetime(2026, 7, 5, 9, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=visibility,
        repo_id=repo_id,
        tenant_id=tenant_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )
