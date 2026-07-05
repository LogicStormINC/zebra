from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_follow_through_verification_outcomes_classify_admin_override(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    SQLiteMemoryStore(database_path).upsert(
        _memory_record(
            memory_id="00000000-0000-0000-0000-000000001111",
            session_id=session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Oldest pending repo memory.",
            status=MemoryStatus.CANDIDATE,
            repo_id=str(workspace.resolve()),
            timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
    )

    result = execute(
        [
            "memory-overdue-retention-breach-follow-through-verification-outcomes",
            str(session_id),
            "--as-of",
            "2026-08-20T06:00:00+00:00",
            "--database",
            str(database_path),
        ]
    )

    assert (
        result.command
        == "memory-overdue-retention-breach-follow-through-verification-outcomes"
    )
    assert result.payload[
        "overdue_retention_breach_follow_through_verification_outcome_counts"
    ] == {"awaiting_admin_override_verification_outcome": 1}
    assert (
        result.payload[
            "highest_priority_overdue_retention_breach_follow_through_verification_outcome"
        ]
        == "awaiting_admin_override_verification_outcome"
    )
    assert (
        result.payload[
            "highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope_kind"
        ]
        == "repo"
    )


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory overdue retention breach follow-through verification outcomes",
            user_input="Inspect overdue retention breach follow-through verification outcomes.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    completed = bootstrap.session.model_copy(
        update={"status": bootstrap.session.status.COMPLETED, "current_sequence": 3}
    )
    event_store.append(
        SessionEvent.create(
            session_id=completed.session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"reason": "done"},
            created_at=datetime(2026, 7, 8, 9, 0, tzinfo=UTC),
        )
    )
    SQLiteProjectionStore(database_path).save_session(completed)
    return completed.session_id


def _memory_record(
    *,
    memory_id: str,
    session_id: SessionId,
    visibility: MemoryVisibility,
    memory_type: MemoryType,
    text: str,
    status: MemoryStatus,
    timestamp: datetime,
    repo_id: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=status,
        visibility=visibility,
        repo_id=repo_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=timestamp,
        updated_at=timestamp,
    )
