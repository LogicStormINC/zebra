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


def test_api_preview_session_memory_queue_rejects_invalid_session_id(
    tmp_path: Path,
) -> None:
    response = create_app(tmp_path / "memory.sqlite").preview_session_memory_queue(
        "not-a-uuid",
        {"decision": "confirm"},
    )

    assert response.status_code == 400
    assert response.body == {
        "session_id": "not-a-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }


def test_api_preview_session_memory_queue_filters_to_current_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace, title="queue-preview-a")
    other_session_id = _seed_completed_session(
        database_path, workspace, title="queue-preview-b"
    )
    current_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000261",
        session_id=session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Run make check after preview.",
    )
    other_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000262",
        session_id=other_session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Other session candidate should stay outside preview.",
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(current_candidate)
    store.upsert(other_candidate)

    response = create_app(database_path).preview_session_memory_queue(
        str(session_id),
        {"decision": "confirm"},
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session_id)
    assert response.body["decision"] == "confirm"
    assert response.body["queue_sweep_preview"] is True
    assert response.body["queued_count"] == 1
    assert response.body["target_scope_kind"] == "session"
    assert response.body["target_scope_id"] == str(session_id)
    assert response.body["target_reason_counts"] == {"repo_candidate_for_session": 1}
    assert response.body["target_explanations"] == [
        {
            "memory_id": str(current_candidate.memory_id),
            "memory_type": "procedure",
            "current_status": "candidate",
            "target_scope_kind": "session",
            "target_scope_id": str(session_id),
            "target_reason": "repo_candidate_for_session",
        }
    ]
    assert response.body["projected_applied_count"] == 1
    assert response.body["projected_memory_status"] == "confirmed"
    assert response.body["projected_by_type"] == {"procedure": 1}
    assert response.body["projected_results"] == [
        {
            "memory_id": str(current_candidate.memory_id),
            "memory_type": "procedure",
            "current_status": "candidate",
            "projected_status": "confirmed",
        }
    ]
    assert response.body["memory_ids"] == [str(current_candidate.memory_id)]
    assert len(response.body["memories"]) == 1
    assert response.body["memories"][0]["memory_id"] == str(current_candidate.memory_id)
    assert store.get(current_candidate.memory_id).status is MemoryStatus.CANDIDATE
    assert store.get(other_candidate.memory_id).status is MemoryStatus.CANDIDATE


def test_route_adapter_handles_tenant_memory_review_queue_preview(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace, title="tenant-queue-preview")
    candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000263",
        session_id=session_id,
        visibility=MemoryVisibility.TENANT,
        tenant_id="tenant-1",
        memory_type=MemoryType.PROCEDURE,
        text="Preview tenant queue review.",
    )
    SQLiteMemoryStore(database_path).upsert(candidate)

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path="/tenants/tenant-1/memory/review-queue-preview",
            body={"decision": "expire"},
        )
    )

    assert response.status_code == 200
    assert response.body["tenant_id"] == "tenant-1"
    assert response.body["decision"] == "expire"
    assert response.body["queue_sweep_preview"] is True
    assert response.body["queued_count"] == 1
    assert response.body["target_scope_kind"] == "tenant"
    assert response.body["target_scope_id"] == "tenant-1"
    assert response.body["target_reason_counts"] == {"tenant_candidate_for_tenant": 1}
    assert response.body["target_explanations"][0]["target_reason"] == "tenant_candidate_for_tenant"
    assert response.body["projected_applied_count"] == 1
    assert response.body["projected_memory_status"] == "expired"
    assert response.body["projected_by_type"] == {"procedure": 1}
    assert response.body["projected_results"][0]["projected_status"] == "expired"
    assert response.body["memories"][0]["status"] == "candidate"


def test_api_preview_session_memory_queue_filters_by_memory_type(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace, title="queue-preview-filter")
    procedure_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000264",
        session_id=session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Procedure candidate stays in filtered preview.",
    )
    preference_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000265",
        session_id=session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        memory_type=MemoryType.PREFERENCE,
        text="Preference candidate is filtered out.",
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(procedure_candidate)
    store.upsert(preference_candidate)

    response = create_app(database_path).preview_session_memory_queue(
        str(session_id),
        {"decision": "confirm", "memory_type": "procedure"},
    )

    assert response.status_code == 200
    assert response.body["memory_type_filter"] == "procedure"
    assert response.body["filtered_from_queued_count"] == 2
    assert response.body["queued_count"] == 1
    assert response.body["memory_ids"] == [str(procedure_candidate.memory_id)]
    assert response.body["projected_by_type"] == {"procedure": 1}
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
    tenant_id: str | None = None,
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
        tenant_id=tenant_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )
