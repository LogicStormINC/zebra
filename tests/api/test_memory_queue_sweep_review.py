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


def test_api_review_session_memory_queue_filters_to_current_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace, title="queue-review-a")
    other_session_id = _seed_completed_session(
        database_path, workspace, title="queue-review-b"
    )
    current_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000231",
        session_id=session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Run make check after queue sweep.",
    )
    other_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000232",
        session_id=other_session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Other session candidate should stay untouched.",
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(current_candidate)
    store.upsert(other_candidate)

    response = create_app(database_path).review_session_memory_queue(
        str(session_id),
        {"decision": "confirm", "operator": "alice", "reason": "queue sweep"},
    )

    updated_current = store.get(current_candidate.memory_id)
    updated_other = store.get(other_candidate.memory_id)

    assert response.status_code == 200
    assert response.body["session_id"] == str(session_id)
    assert response.body["queue_sweep"] is True
    assert response.body["queued_count"] == 1
    assert response.body["applied_count"] == 1
    assert response.body["results"][0]["memory_id"] == str(current_candidate.memory_id)
    assert updated_current is not None
    assert updated_current.status is MemoryStatus.CONFIRMED
    assert updated_other is not None
    assert updated_other.status is MemoryStatus.CANDIDATE


def test_route_adapter_handles_user_memory_review_queue(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace, title="user-queue")
    candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000233",
        session_id=session_id,
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
    )
    SQLiteMemoryStore(database_path).upsert(candidate)

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path="/users/user-1/memory/review-queue",
            body={"decision": "expire", "operator": "alice", "reason": "queue sweep"},
        )
    )

    assert response.status_code == 200
    assert response.body["user_id"] == "user-1"
    assert response.body["queue_sweep"] is True
    assert response.body["queued_count"] == 1
    assert response.body["results"][0]["memory_status"] == "expired"


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
