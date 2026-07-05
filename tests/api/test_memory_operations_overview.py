from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_api_memory_operations_overview_combines_scopes(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_session(database_path, workspace)
    store = SQLiteMemoryStore(database_path)
    store.upsert(
        _memory_record(
            "00000000-0000-0000-0000-000000000261",
            session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Repo pending memory.",
            repo_id=str(workspace.resolve()),
            updated_at=datetime(2026, 7, 7, 9, 0, tzinfo=UTC),
        )
    )
    store.upsert(
        _memory_record(
            "00000000-0000-0000-0000-000000000262",
            session_id,
            visibility=MemoryVisibility.USER,
            memory_type=MemoryType.PREFERENCE,
            text="User pending memory.",
            user_id="user-1",
            updated_at=datetime(2026, 7, 7, 10, 0, tzinfo=UTC),
        )
    )
    store.upsert(
        _memory_record(
            "00000000-0000-0000-0000-000000000263",
            session_id,
            visibility=MemoryVisibility.TENANT,
            memory_type=MemoryType.PROJECT_RULE,
            text="Tenant pending memory.",
            tenant_id="tenant-1",
            updated_at=datetime(2026, 7, 7, 11, 0, tzinfo=UTC),
        )
    )

    response = create_app(database_path).get_memory_operations_overview(
        str(session_id),
        {"user_id": "user-1", "tenant_id": "tenant-1"},
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session_id)
    assert response.body["scope_count"] == 3
    assert response.body["total_pending_count"] == 3
    assert [scope["scope_kind"] for scope in response.body["scopes"]] == [
        "repo",
        "user",
        "tenant",
    ]


def test_route_adapter_handles_memory_operations_overview(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_session(database_path, workspace)

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/memory-overview",
            body={"user_id": "user-1"},
        )
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session_id)
    assert response.body["scope_count"] == 2
    assert response.body["scopes"][1]["scope_kind"] == "user"


def _seed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory operations overview",
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
    memory_id: str,
    session_id: SessionId,
    *,
    visibility: MemoryVisibility,
    memory_type: MemoryType,
    text: str,
    updated_at: datetime,
    repo_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
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
        tenant_id=tenant_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=updated_at,
        updated_at=updated_at,
    )
