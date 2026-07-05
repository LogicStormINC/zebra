from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_api_memory_backlog_pressure_signals_classify_highest_pressure_scope(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    store = SQLiteMemoryStore(database_path)
    store.upsert(
        _memory_record(
            memory_id="00000000-0000-0000-0000-000000000381",
            session_id=session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Stale pending repo memory.",
            status=MemoryStatus.CANDIDATE,
            repo_id=str(workspace.resolve()),
            timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
    )
    reviewed_user = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000382",
        session_id=session_id,
        visibility=MemoryVisibility.USER,
        memory_type=MemoryType.PREFERENCE,
        text="Recently reviewed user memory.",
        status=MemoryStatus.CONFIRMED,
        user_id="user-1",
        timestamp=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
    )
    store.upsert(reviewed_user)
    _append_review_event(
        database_path=database_path,
        session_id=session_id,
        sequence=4,
        memory_id=str(reviewed_user.memory_id),
        memory_type=reviewed_user.memory_type.value,
        created_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
    )

    response = create_app(database_path).get_memory_backlog_pressure_signals(
        str(session_id),
        {"user_id": "user-1", "as_of": "2026-07-09T00:00:00+00:00"},
    )

    assert response.status_code == 200
    assert response.body["scope_count"] == 2
    assert response.body["total_pending_count"] == 1
    assert response.body["total_reviewed_last_24h_count"] == 1
    assert response.body["pressure_level_counts"] == {"high": 1, "clear": 1}
    assert response.body["highest_pressure_level"] == "high"
    assert response.body["highest_pressure_scope_kind"] == "repo"
    assert response.body["highest_pressure_reasons"] == ["stale_backlog", "no_recent_reviews"]
    repo_scope = response.body["scopes"][0]
    user_scope = response.body["scopes"][1]
    assert repo_scope["pressure_level"] == "high"
    assert user_scope["pressure_level"] == "clear"


def test_route_adapter_handles_memory_backlog_pressure_signals(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/memory-pressure",
            body={"tenant_id": "tenant-1", "as_of": "2026-07-09T00:00:00+00:00"},
        )
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session_id)
    assert response.body["scope_count"] == 2
    assert response.body["scopes"][1]["scope_kind"] == "tenant"


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory pressure signals",
            user_input="Inspect backlog pressure.",
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


def _append_review_event(
    *,
    database_path: Path,
    session_id: SessionId,
    sequence: int,
    memory_id: str,
    memory_type: str,
    created_at: datetime,
) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=EventType.MEMORY_REVIEW_RECORDED,
            actor=EventActor.USER,
            payload={
                "memory_id": memory_id,
                "memory_type": memory_type,
                "previous_status": "candidate",
                "status": "confirmed",
                "operator": "alice",
                "reason": "validated",
                "superseded_memory_ids": [],
                "duplicate_of_memory_id": None,
            },
            created_at=created_at,
        )
    )


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
    user_id: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=status,
        visibility=visibility,
        repo_id=repo_id,
        user_id=user_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=timestamp,
        updated_at=timestamp,
    )
