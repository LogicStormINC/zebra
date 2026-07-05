from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_cli.cli import execute


def test_user_memory_queue_summary_contract_matrix_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    api_database_path = tmp_path / "api.sqlite"
    cli_database_path = tmp_path / "cli.sqlite"
    api_workspace = tmp_path / "api-workspace"
    cli_workspace = tmp_path / "cli-workspace"
    api_workspace.mkdir()
    cli_workspace.mkdir()
    api_session_id = _seed_session(api_database_path, api_workspace)
    cli_session_id = _seed_session(cli_database_path, cli_workspace)
    api_store = SQLiteMemoryStore(api_database_path)
    cli_store = SQLiteMemoryStore(cli_database_path)
    api_store.upsert(
        _memory_record(
            "00000000-0000-0000-0000-000000000251",
            api_session_id,
            updated_at=datetime(2026, 7, 6, 9, 0, tzinfo=UTC),
        )
    )
    cli_store.upsert(
        _memory_record(
            "00000000-0000-0000-0000-000000000252",
            cli_session_id,
            updated_at=datetime(2026, 7, 6, 9, 0, tzinfo=UTC),
        )
    )

    http_response = TestClient(create_http_app(api_database_path)).get(
        "/users/user-1/memory/queue-summary"
    )
    cli_result = execute(
        ["memory-user-queue-summary", "user-1", "--database", str(cli_database_path)]
    )

    assert http_response.status_code == 200
    assert _normalize_http(http_response.json()) == _normalize_cli(cli_result.payload)


def _normalize_http(payload: dict[str, object]) -> dict[str, object]:
    return {
        "pending_count": payload["pending_count"],
        "queue_status": payload["queue_status"],
        "has_latest": payload["latest_memory_id"] is not None,
        "has_latest_updated_at": payload["latest_updated_at"] is not None,
    }


def _normalize_cli(payload: dict[str, object]) -> dict[str, object]:
    return {
        "pending_count": payload["pending_count"],
        "queue_status": payload["queue_status"],
        "has_latest": payload["latest_memory_id"] is not None,
        "has_latest_updated_at": payload["latest_updated_at"] is not None,
    }


def _seed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory scope queue summary matrix",
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
    updated_at: datetime,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=updated_at,
        updated_at=updated_at,
    )
