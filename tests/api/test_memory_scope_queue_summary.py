from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_api_get_user_memory_queue_summary_returns_pending_counts(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_session(database_path, workspace)
    first = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000231",
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        source_session_id=session_id,
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
        status=MemoryStatus.CANDIDATE,
        updated_at=datetime(2026, 7, 6, 9, 0, tzinfo=UTC),
    )
    latest = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000232",
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        source_session_id=session_id,
        memory_type=MemoryType.PREFERENCE,
        text="Keep summaries short.",
        status=MemoryStatus.CANDIDATE,
        updated_at=datetime(2026, 7, 6, 10, 0, tzinfo=UTC),
    )
    confirmed = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000233",
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        source_session_id=session_id,
        memory_type=MemoryType.PREFERENCE,
        text="Confirmed preference.",
        status=MemoryStatus.CONFIRMED,
        updated_at=datetime(2026, 7, 6, 11, 0, tzinfo=UTC),
    )
    store = SQLiteMemoryStore(database_path)
    store.upsert(first)
    store.upsert(latest)
    store.upsert(confirmed)

    response = create_app(database_path).get_user_memory_queue_summary("user-1")

    assert response.status_code == 200
    assert response.body == {
        "user_id": "user-1",
        "pending_count": 2,
        "queue_status": "pending",
        "latest_memory_id": str(latest.memory_id),
        "latest_updated_at": "2026-07-06T10:00:00+00:00",
    }


def test_route_adapter_handles_tenant_memory_queue_summary(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_session(database_path, workspace)
    candidate = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000234",
        visibility=MemoryVisibility.TENANT,
        tenant_id="tenant-1",
        source_session_id=session_id,
        memory_type=MemoryType.PROJECT_RULE,
        text="Use the repo default commands: `make sync`, `make check`.",
        status=MemoryStatus.CANDIDATE,
        updated_at=datetime(2026, 7, 6, 9, 30, tzinfo=UTC),
    )
    SQLiteMemoryStore(database_path).upsert(candidate)

    response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(method="GET", path="/tenants/tenant-1/memory/queue-summary")
    )

    assert response.status_code == 200
    assert response.body["tenant_id"] == "tenant-1"
    assert response.body["pending_count"] == 1
    assert response.body["queue_status"] == "pending"


def _seed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory scope queue summary",
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
    *,
    memory_id: str,
    visibility: MemoryVisibility,
    source_session_id: SessionId,
    memory_type: MemoryType,
    text: str,
    status: MemoryStatus,
    updated_at: datetime,
    user_id: str | None = None,
    tenant_id: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=status,
        visibility=visibility,
        user_id=user_id,
        tenant_id=tenant_id,
        source_session_id=source_session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=updated_at,
        updated_at=updated_at,
    )
