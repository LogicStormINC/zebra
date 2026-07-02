from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.sessions import Session
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_cli.cli import execute


def test_session_memory_contract_matrix_matches_across_api_and_cli(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)
    record = _memory_record(
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
    )
    SQLiteMemoryStore(database_path).upsert(record)

    http_response = TestClient(create_http_app(database_path)).get(f"/sessions/{session_id}/memory")
    cli_result = execute(["memory", str(session_id), "--database", str(database_path)])

    assert http_response.status_code == 200
    assert _normalize_http_payload(
        http_response.json()
    ) == _normalize_cli_payload(cli_result.payload)


def test_session_memory_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    http_response = TestClient(create_http_app(database_path)).get(f"/sessions/{session_id}/memory")
    cli_result = execute(["memory", session_id, "--database", str(database_path)])

    assert http_response.status_code == 404
    assert _normalize_http_payload(
        http_response.json()
    ) == _normalize_cli_payload(cli_result.payload)


def test_session_memory_contract_matrix_unavailable_scope_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="No memory scope")
    )

    http_response = TestClient(create_http_app(database_path)).get(
        f"/sessions/{session.session_id}/memory"
    )
    cli_result = execute(
        [
            "memory",
            str(session.session_id),
            "--database",
            str(database_path),
        ]
    )

    assert http_response.status_code == 409
    assert _normalize_http_payload(
        http_response.json()
    ) == _normalize_cli_payload(cli_result.payload)


def _normalize_http_payload(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("status") in {"not_found", "memory_unavailable"}:
        normalized = {
            "session_id": payload["session_id"],
            "status": payload["status"],
        }
        if "reason" in payload:
            normalized["reason"] = payload["reason"]
        return normalized
    return {
        "session_id": payload["session_id"],
        "status": "ok",
        "repo_id": payload["repo_id"],
        "memories": payload["memories"],
    }


def _normalize_cli_payload(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("status") in {"not_found", "memory_unavailable"}:
        normalized = {
            "session_id": payload["session_id"],
            "status": payload["status"],
        }
        if "reason" in payload:
            normalized["reason"] = payload["reason"]
        return normalized
    return {
        "session_id": payload["session_id"],
        "status": "ok",
        "repo_id": payload["repo_id"],
        "memories": payload["memories"],
    }


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory matrix",
            user_input="Inspect memories.",
            workspace_root=workspace_root.resolve(),
        )
    )
    for event in bootstrap.events:
        SQLiteEventStore(database_path).append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _memory_record(*, repo_id: str, source_session_id: SessionId) -> MemoryRecord:
    created_at = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000113")),
        memory_type=MemoryType.PROCEDURE,
        text="run targeted pytest before make check",
        confidence=0.85,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id=repo_id,
        source_session_id=source_session_id,
        created_at=created_at,
        updated_at=created_at,
    )
