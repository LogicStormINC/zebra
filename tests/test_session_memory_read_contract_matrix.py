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


def test_session_memory_read_contract_matrix_matches_last_review_shape(
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
    api_record = _expired_record(api_session_id, str(api_workspace.resolve()))
    cli_record = _expired_record(cli_session_id, str(cli_workspace.resolve()))
    SQLiteMemoryStore(api_database_path).upsert(api_record)
    SQLiteMemoryStore(cli_database_path).upsert(cli_record)
    _append_tool_source_event(api_database_path, api_session_id)
    _append_tool_source_event(cli_database_path, cli_session_id)
    _append_review_event(api_database_path, api_session_id, api_record)
    _append_review_event(cli_database_path, cli_session_id, cli_record)

    http_response = TestClient(create_http_app(api_database_path)).get(
        f"/sessions/{api_session_id}/memory"
    )
    cli_result = execute(
        ["memory", str(cli_session_id), "--database", str(cli_database_path)]
    )

    assert http_response.status_code == 200
    assert _normalize_http(http_response.json()) == _normalize_cli(cli_result.payload)


def test_session_memory_read_contract_matrix_matches_source_provenance_shape(
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
    api_record = _expired_record(api_session_id, str(api_workspace.resolve()))
    cli_record = _expired_record(cli_session_id, str(cli_workspace.resolve()))
    SQLiteMemoryStore(api_database_path).upsert(api_record)
    SQLiteMemoryStore(cli_database_path).upsert(cli_record)
    _append_tool_source_event(api_database_path, api_session_id)
    _append_tool_source_event(cli_database_path, cli_session_id)
    _append_review_event(api_database_path, api_session_id, api_record)
    _append_review_event(cli_database_path, cli_session_id, cli_record)

    http_response = TestClient(create_http_app(api_database_path)).get(
        f"/sessions/{api_session_id}/memory"
    )
    cli_result = execute(
        ["memory", str(cli_session_id), "--database", str(cli_database_path)]
    )

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
            title="Memory read matrix",
            user_input="Inspect memories.",
            workspace_root=workspace_root.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _expired_record(session_id: SessionId, repo_id: str) -> MemoryRecord:
    created_at = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000151")),
        memory_type=MemoryType.PROJECT_RULE,
        text="Use make check before push.",
        confidence=0.8,
        status=MemoryStatus.EXPIRED,
        visibility=MemoryVisibility.REPO,
        repo_id=repo_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )


def _append_review_event(database_path: Path, session_id: SessionId, record: MemoryRecord) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.MEMORY_REVIEW_RECORDED,
            actor=EventActor.HARNESS,
            payload={
                "memory_id": str(record.memory_id),
                "memory_type": record.memory_type.value,
                "previous_status": "confirmed",
                "status": "expired",
                "operator": "system",
                "reason": "stale after AGENTS.md refresh",
                "superseded_memory_ids": [],
                "duplicate_of_memory_id": None,
            },
            created_at=datetime(2026, 7, 3, 9, 30, tzinfo=UTC),
        )
    )


def _append_tool_source_event(database_path: Path, session_id: SessionId) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "attempt_number": 1,
                "tool_name": "files.read",
                "status": "executed",
                "output": "# Zebra Agent Repository Rules",
                "metadata": {
                    "path": "AGENTS.md",
                    "byte_count": 32,
                    "truncated": False,
                },
            },
            created_at=datetime(2026, 7, 3, 9, 0, tzinfo=UTC),
        )
    )
