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


def test_memory_backlog_pressure_signals_contract_matrix_matches_across_api_and_cli(
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
    SQLiteMemoryStore(api_database_path).upsert(
        _memory_record(
            memory_id="00000000-0000-0000-0000-000000000401",
            session_id=api_session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Stale pending repo memory.",
            status=MemoryStatus.CANDIDATE,
            repo_id=str(api_workspace.resolve()),
            timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
    )
    reviewed_user = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000402",
        session_id=api_session_id,
        visibility=MemoryVisibility.USER,
        memory_type=MemoryType.PREFERENCE,
        text="Recently reviewed user memory.",
        status=MemoryStatus.CONFIRMED,
        user_id="user-1",
        timestamp=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
    )
    SQLiteMemoryStore(api_database_path).upsert(reviewed_user)
    _append_review_event(
        database_path=api_database_path,
        session_id=api_session_id,
        sequence=4,
        memory_id=str(reviewed_user.memory_id),
        memory_type=reviewed_user.memory_type.value,
        created_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
    )

    SQLiteMemoryStore(cli_database_path).upsert(
        _memory_record(
            memory_id="00000000-0000-0000-0000-000000000403",
            session_id=cli_session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Stale pending repo memory.",
            status=MemoryStatus.CANDIDATE,
            repo_id=str(cli_workspace.resolve()),
            timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
    )
    reviewed_user_cli = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000404",
        session_id=cli_session_id,
        visibility=MemoryVisibility.USER,
        memory_type=MemoryType.PREFERENCE,
        text="Recently reviewed user memory.",
        status=MemoryStatus.CONFIRMED,
        user_id="user-1",
        timestamp=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
    )
    SQLiteMemoryStore(cli_database_path).upsert(reviewed_user_cli)
    _append_review_event(
        database_path=cli_database_path,
        session_id=cli_session_id,
        sequence=4,
        memory_id=str(reviewed_user_cli.memory_id),
        memory_type=reviewed_user_cli.memory_type.value,
        created_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
    )

    http_response = TestClient(create_http_app(api_database_path)).post(
        f"/sessions/{api_session_id}/memory-pressure",
        json={"user_id": "user-1", "as_of": "2026-07-09T00:00:00+00:00"},
    )
    cli_result = execute(
        [
            "memory-pressure",
            str(cli_session_id),
            "--user-id",
            "user-1",
            "--as-of",
            "2026-07-09T00:00:00+00:00",
            "--database",
            str(cli_database_path),
        ]
    )

    assert http_response.status_code == 200
    assert _normalize_http(http_response.json()) == _normalize_cli(cli_result.payload)


def _normalize_http(payload: dict[str, object]) -> dict[str, object]:
    return {
        "reference_at": payload["reference_at"],
        "scope_count": payload["scope_count"],
        "total_pending_count": payload["total_pending_count"],
        "total_reviewed_last_24h_count": payload["total_reviewed_last_24h_count"],
        "pressure_level_counts": payload["pressure_level_counts"],
        "highest_pressure_level": payload["highest_pressure_level"],
        "highest_pressure_scope_kind": payload["highest_pressure_scope_kind"],
        "highest_pressure_reasons": payload["highest_pressure_reasons"],
    }


def _normalize_cli(payload: dict[str, object]) -> dict[str, object]:
    return {
        "reference_at": payload["reference_at"],
        "scope_count": payload["scope_count"],
        "total_pending_count": payload["total_pending_count"],
        "total_reviewed_last_24h_count": payload["total_reviewed_last_24h_count"],
        "pressure_level_counts": payload["pressure_level_counts"],
        "highest_pressure_level": payload["highest_pressure_level"],
        "highest_pressure_scope_kind": payload["highest_pressure_scope_kind"],
        "highest_pressure_reasons": payload["highest_pressure_reasons"],
    }


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory pressure signals matrix",
            user_input="Inspect backlog pressure.",
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
            created_at=datetime(2026, 7, 8, 9, 0, tzinfo=UTC),
        )
    )
    SQLiteProjectionStore(database_path).save_session(completed)
    return completed.session_id


def _append_review_event(
    *,
    database_path: Path,
    session_id: SessionId,
    sequence: int,
    memory_id: str,
    memory_type: str,
    created_at: datetime,
) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=EventType.MEMORY_REVIEW_RECORDED,
            actor=EventActor.USER,
            payload={
                "memory_id": memory_id,
                "memory_type": memory_type,
                "previous_status": "candidate",
                "status": "confirmed",
                "operator": "alice",
                "reason": "validated",
                "superseded_memory_ids": [],
                "duplicate_of_memory_id": None,
            },
            created_at=created_at,
        )
    )


def _memory_record(
    *,
    memory_id: str,
    session_id: SessionId,
    visibility: MemoryVisibility,
    memory_type: MemoryType,
    text: str,
    status: MemoryStatus,
    timestamp: datetime,
    repo_id: str | None = None,
    user_id: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=status,
        visibility=visibility,
        repo_id=repo_id,
        user_id=user_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=timestamp,
        updated_at=timestamp,
    )
