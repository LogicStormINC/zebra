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


def test_api_bulk_review_user_memory_reports_applied_skipped_and_invalid(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000201",
        session_id=session_id,
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(candidate)

    response = create_app(database_path).bulk_review_user_memory(
        "user-1",
        {
            "decision": "confirm",
            "memory_ids": [
                str(candidate.memory_id),
                str(candidate.memory_id),
                "not-a-uuid",
                "00000000-0000-0000-0000-000000000299",
            ],
            "operator": "alice",
            "reason": "bulk triage",
        },
    )

    assert response.status_code == 200
    assert response.body["user_id"] == "user-1"
    assert response.body["decision"] == "confirm"
    assert response.body["applied_count"] == 1
    assert response.body["skipped_count"] == 2
    assert response.body["invalid_count"] == 1
    assert response.body["results"] == [
        {
            "outcome": "applied",
            "session_id": str(session_id),
            "user_id": "user-1",
            "memory_id": str(candidate.memory_id),
            "decision": "confirm",
            "event_type": "memory_review_recorded",
            "sequence": 4,
            "status": "completed",
            "memory_status": "confirmed",
            "superseded_memory_ids": [],
            "duplicate_of_memory_id": None,
        },
        {
            "memory_id": str(candidate.memory_id),
            "outcome": "skipped",
            "status": "duplicate_request",
            "reason": "memory_id was requested more than once",
        },
        {
            "memory_id": "not-a-uuid",
            "outcome": "invalid",
            "status": "invalid_id",
            "reason": "memory_id must be a valid UUID",
        },
        {
            "memory_id": "00000000-0000-0000-0000-000000000299",
            "outcome": "skipped",
            "status": "not_found",
        },
    ]


def test_route_adapter_handles_tenant_bulk_memory_review(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000202",
        session_id=session_id,
        visibility=MemoryVisibility.TENANT,
        tenant_id="tenant-1",
        memory_type=MemoryType.PROJECT_RULE,
        text="Use the repo default commands: `make sync`, `make check`.",
    )
    SQLiteMemoryStore(database_path).upsert(candidate)

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path="/tenants/tenant-1/memory/bulk-review",
            body={
                "decision": "expire",
                "memory_ids": [str(candidate.memory_id)],
                "operator": "alice",
                "reason": "stale tenant rule",
            },
        )
    )

    assert response.status_code == 200
    assert response.body["tenant_id"] == "tenant-1"
    assert response.body["applied_count"] == 1
    assert response.body["results"][0]["memory_status"] == "expired"


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory scope bulk review",
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
    user_id: str | None = None,
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
        user_id=user_id,
        tenant_id=tenant_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )
