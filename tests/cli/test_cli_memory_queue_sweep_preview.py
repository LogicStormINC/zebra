from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_memory_review_queue_preview_filters_to_current_session(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace, title="cli-preview-a")
    other_session_id = _seed_completed_session(database_path, workspace, title="cli-preview-b")
    current_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000271",
        session_id=session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Preview session queue.",
    )
    other_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000272",
        session_id=other_session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Other session candidate should stay outside preview.",
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(current_candidate)
    store.upsert(other_candidate)

    result = execute(
        [
            "memory-review-queue-preview",
            str(session_id),
            "--decision",
            "confirm",
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "memory-review-queue-preview"
    assert result.payload["session_id"] == str(session_id)
    assert result.payload["decision"] == "confirm"
    assert result.payload["queue_sweep_preview"] is True
    assert result.payload["queued_count"] == 1
    assert result.payload["target_scope_kind"] == "session"
    assert result.payload["target_scope_id"] == str(session_id)
    assert result.payload["target_reason_counts"] == {"repo_candidate_for_session": 1}
    assert result.payload["target_explanations"] == [
        {
            "memory_id": str(current_candidate.memory_id),
            "memory_type": "procedure",
            "current_status": "candidate",
            "target_scope_kind": "session",
            "target_scope_id": str(session_id),
            "target_reason": "repo_candidate_for_session",
        }
    ]
    assert result.payload["projected_applied_count"] == 1
    assert result.payload["projected_memory_status"] == "confirmed"
    assert result.payload["projected_by_type"] == {"procedure": 1}
    assert result.payload["projected_results"] == [
        {
            "memory_id": str(current_candidate.memory_id),
            "memory_type": "procedure",
            "current_status": "candidate",
            "projected_status": "confirmed",
        }
    ]
    assert result.payload["memory_ids"] == [str(current_candidate.memory_id)]
    assert len(result.payload["memories"]) == 1
    assert result.payload["memories"][0]["memory_id"] == str(current_candidate.memory_id)
    assert store.get(current_candidate.memory_id).status is MemoryStatus.CANDIDATE
    assert store.get(other_candidate.memory_id).status is MemoryStatus.CANDIDATE


def test_cli_memory_user_review_queue_preview_keeps_candidates_pending(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace, title="cli-user-preview")
    candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000273",
        session_id=session_id,
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        memory_type=MemoryType.PREFERENCE,
        text="Preview user queue.",
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(candidate)

    result = execute(
        [
            "memory-user-review-queue-preview",
            "user-1",
            "--decision",
            "expire",
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "memory-user-review-queue-preview"
    assert result.payload["user_id"] == "user-1"
    assert result.payload["decision"] == "expire"
    assert result.payload["queue_sweep_preview"] is True
    assert result.payload["queued_count"] == 1
    assert result.payload["target_scope_kind"] == "user"
    assert result.payload["target_scope_id"] == "user-1"
    assert result.payload["target_reason_counts"] == {"user_candidate_for_user": 1}
    assert result.payload["target_explanations"][0]["target_reason"] == "user_candidate_for_user"
    assert result.payload["projected_applied_count"] == 1
    assert result.payload["projected_memory_status"] == "expired"
    assert result.payload["projected_by_type"] == {"preference": 1}
    assert result.payload["projected_results"][0]["projected_status"] == "expired"
    assert result.payload["memories"][0]["status"] == "candidate"
    assert store.get(candidate.memory_id).status is MemoryStatus.CANDIDATE


def test_cli_memory_review_queue_preview_filters_by_memory_type(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace, title="cli-preview-filter")
    procedure_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000274",
        session_id=session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Procedure candidate stays in filtered preview.",
    )
    preference_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000275",
        session_id=session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PREFERENCE,
        text="Preference candidate is filtered out.",
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(procedure_candidate)
    store.upsert(preference_candidate)

    result = execute(
        [
            "memory-review-queue-preview",
            str(session_id),
            "--decision",
            "confirm",
            "--memory-type",
            "procedure",
            "--database",
            str(database_path),
        ]
    )

    assert result.command == "memory-review-queue-preview"
    assert result.payload["memory_type_filter"] == "procedure"
    assert result.payload["filtered_from_queued_count"] == 2
    assert result.payload["queued_count"] == 1
    assert result.payload["memory_ids"] == [str(procedure_candidate.memory_id)]
    assert result.payload["projected_by_type"] == {"procedure": 1}
    assert store.get(procedure_candidate.memory_id).status is MemoryStatus.CANDIDATE
    assert store.get(preference_candidate.memory_id).status is MemoryStatus.CANDIDATE


def _seed_completed_session(
    database_path: Path,
    workspace_root: Path,
    *,
    title: str,
) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=title,
            user_input="Inspect memories.",
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
            created_at=datetime(2026, 7, 6, 9, 0, tzinfo=UTC),
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
    user_id: str | None = None,
) -> MemoryRecord:
    created_at = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=visibility,
        repo_id=repo_id,
        user_id=user_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )
