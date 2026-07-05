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


def test_user_memory_review_contract_matrix_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    api_database_path = tmp_path / "api.sqlite"
    cli_database_path = tmp_path / "cli.sqlite"
    api_workspace = tmp_path / "api-workspace"
    cli_workspace = tmp_path / "cli-workspace"
    api_workspace.mkdir()
    cli_workspace.mkdir()
    api_session_id = _seed_completed_session(api_database_path, api_workspace)
    cli_session_id = _seed_completed_session(cli_database_path, cli_workspace)
    api_record = _candidate_record(api_session_id)
    cli_record = _candidate_record(cli_session_id)
    SQLiteMemoryStore(api_database_path).upsert(api_record)
    SQLiteMemoryStore(cli_database_path).upsert(cli_record)

    http_response = TestClient(create_http_app(api_database_path)).post(
        f"/users/user-1/memory/{api_record.memory_id}/confirm",
        json={},
    )
    cli_result = execute(
        [
            "memory-user-review",
            "user-1",
            str(cli_record.memory_id),
            "--decision",
            "confirm",
            "--database",
            str(cli_database_path),
        ]
    )

    assert http_response.status_code == 200
    assert _normalize_http(http_response.json()) == _normalize_cli(cli_result.payload)


def _normalize_http(payload: dict[str, object]) -> dict[str, object]:
    return {
        "decision": payload["decision"],
        "event_type": payload["event_type"],
        "sequence": payload["sequence"],
        "status": payload["status"],
        "memory_status": payload["memory_status"],
        "superseded_memory_ids": payload["superseded_memory_ids"],
        "duplicate_of_memory_id": payload["duplicate_of_memory_id"],
    }


def _normalize_cli(payload: dict[str, object]) -> dict[str, object]:
    return {
        "decision": payload["decision"],
        "event_type": payload["event_type"],
        "sequence": payload["sequence"],
        "status": payload["status"],
        "memory_status": payload["memory_status"],
        "superseded_memory_ids": payload["superseded_memory_ids"],
        "duplicate_of_memory_id": payload["duplicate_of_memory_id"],
    }


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory scope review matrix",
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
            created_at=datetime(2026, 7, 4, 10, 0, tzinfo=UTC),
        )
    )
    SQLiteProjectionStore(database_path).save_session(completed)
    return completed.session_id


def _candidate_record(session_id: SessionId) -> MemoryRecord:
    created_at = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000173")),
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )
