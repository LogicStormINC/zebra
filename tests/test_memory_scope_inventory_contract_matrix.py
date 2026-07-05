from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_cli.cli import execute


def test_user_memory_inventory_contract_matrix_matches_across_api_and_cli(
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
    _append_user_source_event(api_database_path, api_session_id)
    _append_user_source_event(cli_database_path, cli_session_id)
    api_record = _memory_record(api_session_id)
    cli_record = _memory_record(cli_session_id)
    SQLiteMemoryStore(api_database_path).upsert(api_record)
    SQLiteMemoryStore(cli_database_path).upsert(cli_record)

    http_response = TestClient(create_http_app(api_database_path)).get("/users/user-1/memory")
    cli_result = execute(["memory-user", "user-1", "--database", str(cli_database_path)])

    assert http_response.status_code == 200
    assert _normalize_http(http_response.json()) == _normalize_cli(cli_result.payload)


def _normalize_http(payload: dict[str, object]) -> dict[str, object]:
    memory = payload["memories"][0]
    assert isinstance(memory, dict)
    return {
        "memory_type": memory["memory_type"],
        "memory_status": memory["status"],
        "source": memory["source"],
        "last_review": memory["last_review"],
    }


def _normalize_cli(payload: dict[str, object]) -> dict[str, object]:
    memory = payload["memories"][0]
    assert isinstance(memory, dict)
    return {
        "memory_type": memory["memory_type"],
        "memory_status": memory["status"],
        "source": memory["source"],
        "last_review": memory["last_review"],
    }


def _seed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory scope matrix",
            user_input="Inspect memories.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _memory_record(session_id: SessionId) -> MemoryRecord:
    created_at = datetime(2026, 7, 4, 9, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000163")),
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
        confidence=0.8,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )


def _append_user_source_event(database_path: Path, session_id: SessionId) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": "Preference: Prefer concise CLI output."},
            created_at=datetime(2026, 7, 4, 9, 0, tzinfo=UTC),
        )
    )
