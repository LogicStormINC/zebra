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


def test_api_memory_overdue_intervention_hints_classify_next_window_queue(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    SQLiteMemoryStore(database_path).upsert(
        _memory_record(
            memory_id="00000000-0000-0000-0000-000000000931",
            session_id=session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Oldest pending repo memory.",
            status=MemoryStatus.CANDIDATE,
            repo_id=str(workspace.resolve()),
            timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
    )

    response = create_app(database_path).get_memory_overdue_intervention_hints(
        str(session_id),
        {"as_of": "2026-07-11T06:00:00+00:00"},
    )

    assert response.status_code == 200
    assert response.body["overdue_intervention_hint_counts"] == {
        "queue_next_review_window": 1
    }
    assert response.body["highest_priority_overdue_intervention_hint"] == (
        "queue_next_review_window"
    )
    assert response.body["highest_priority_overdue_intervention_priority"] == "low"
    assert response.body["highest_priority_overdue_intervention_scope_kind"] == "repo"
    assert response.body["scopes"][0]["overdue_intervention_hint"] == (
        "queue_next_review_window"
    )


def test_route_adapter_handles_memory_overdue_interventions(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/memory-overdue-interventions",
            body={"tenant_id": "tenant-1", "as_of": "2026-07-11T06:00:00+00:00"},
        )
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session_id)
    assert response.body["scope_count"] == 2
    assert response.body["scopes"][1]["scope_kind"] == "tenant"


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory overdue intervention hints",
            user_input="Inspect overdue interventions.",
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
