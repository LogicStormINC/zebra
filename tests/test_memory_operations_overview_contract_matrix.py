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


def test_memory_operations_overview_contract_matrix_matches_across_api_and_cli(
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
    SQLiteMemoryStore(api_database_path).upsert(
        _memory_record(
            "00000000-0000-0000-0000-000000000281",
            api_session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Repo pending memory.",
            repo_id=str(api_workspace.resolve()),
            updated_at=datetime(2026, 7, 7, 9, 0, tzinfo=UTC),
        )
    )
    SQLiteMemoryStore(cli_database_path).upsert(
        _memory_record(
            "00000000-0000-0000-0000-000000000282",
            cli_session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Repo pending memory.",
            repo_id=str(cli_workspace.resolve()),
            updated_at=datetime(2026, 7, 7, 9, 0, tzinfo=UTC),
        )
    )

    http_response = TestClient(create_http_app(api_database_path)).post(
        f"/sessions/{api_session_id}/memory-overview",
        json={"user_id": "user-1"},
    )
    cli_result = execute(
        [
            "memory-overview",
            str(cli_session_id),
            "--user-id",
            "user-1",
            "--database",
            str(cli_database_path),
        ]
    )

    assert http_response.status_code == 200
    assert _normalize_http(http_response.json()) == _normalize_cli(cli_result.payload)


def _normalize_http(payload: dict[str, object]) -> dict[str, object]:
    scopes = payload["scopes"]
    assert isinstance(scopes, list)
    return {
        "scope_count": payload["scope_count"],
        "total_pending_count": payload["total_pending_count"],
        "scope_kinds": [
            scope["scope_kind"] for scope in scopes if isinstance(scope, dict)
        ],
        "queue_statuses": [
            scope["queue_status"] for scope in scopes if isinstance(scope, dict)
        ],
    }


def _normalize_cli(payload: dict[str, object]) -> dict[str, object]:
    scopes = payload["scopes"]
    assert isinstance(scopes, list)
    return {
        "scope_count": payload["scope_count"],
        "total_pending_count": payload["total_pending_count"],
        "scope_kinds": [
            scope["scope_kind"] for scope in scopes if isinstance(scope, dict)
        ],
        "queue_statuses": [
            scope["queue_status"] for scope in scopes if isinstance(scope, dict)
        ],
    }


def _seed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory operations overview matrix",
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
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=visibility,
        repo_id=repo_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=updated_at,
        updated_at=updated_at,
    )
