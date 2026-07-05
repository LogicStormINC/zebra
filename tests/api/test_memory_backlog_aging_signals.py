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


def test_api_memory_backlog_aging_signals_report_oldest_pending_and_buckets(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    store = SQLiteMemoryStore(database_path)
    store.upsert(
        _memory_record(
            memory_id="00000000-0000-0000-0000-000000000321",
            session_id=session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Fresh repo memory.",
            repo_id=str(workspace.resolve()),
            created_at=datetime(2026, 7, 8, 0, 0, tzinfo=UTC),
        )
    )
    store.upsert(
        _memory_record(
            memory_id="00000000-0000-0000-0000-000000000322",
            session_id=session_id,
            visibility=MemoryVisibility.USER,
            memory_type=MemoryType.PREFERENCE,
            text="Aged user memory.",
            user_id="user-1",
            created_at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
    )

    response = create_app(database_path).get_memory_backlog_aging_signals(
        str(session_id),
        {
            "user_id": "user-1",
            "as_of": "2026-07-09T00:00:00+00:00",
        },
    )

    assert response.status_code == 200
    assert response.body["reference_at"] == "2026-07-09T00:00:00+00:00"
    assert response.body["scope_count"] == 2
    assert response.body["total_pending_count"] == 2
    assert response.body["pending_age_bucket_totals"] == {
        "lt_1d": 0,
        "gte_1d_lt_3d": 1,
        "gte_3d_lt_7d": 0,
        "gte_7d": 1,
    }
    assert response.body["oldest_pending_scope_kind"] == "user"
    assert response.body["oldest_pending_memory_id"] == "00000000-0000-0000-0000-000000000322"
    assert response.body["oldest_pending_age_days"] == 8
    repo_scope = response.body["scopes"][0]
    user_scope = response.body["scopes"][1]
    assert repo_scope["pending_age_buckets"] == {
        "lt_1d": 0,
        "gte_1d_lt_3d": 1,
        "gte_3d_lt_7d": 0,
        "gte_7d": 0,
    }
    assert user_scope["pending_age_buckets"]["gte_7d"] == 1


def test_route_adapter_handles_memory_backlog_aging_signals(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/memory-aging",
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
            title="Memory aging signals",
            user_input="Inspect backlog aging.",
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
    created_at: datetime,
    repo_id: str | None = None,
    user_id: str | None = None,
) -> MemoryRecord:
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
