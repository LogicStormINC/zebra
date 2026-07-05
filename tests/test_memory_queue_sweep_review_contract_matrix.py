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
from zebra_agent_cli.cli import execute


def test_memory_queue_sweep_review_contract_matrix_matches_api_and_cli(
    tmp_path: Path,
) -> None:
    api_database_path = tmp_path / "api-memory.sqlite"
    cli_database_path = tmp_path / "cli-memory.sqlite"
    api_workspace = tmp_path / "api-workspace"
    cli_workspace = tmp_path / "cli-workspace"
    api_workspace.mkdir()
    cli_workspace.mkdir()
    api_session_id = _seed_completed_session(api_database_path, api_workspace)
    cli_session_id = _seed_completed_session(cli_database_path, cli_workspace)
    api_candidate = _candidate_record(
        memory_id="00000000-0000-0000-0000-000000000251",
        session_id=api_session_id,
        visibility=MemoryVisibility.REPO,
        repo_id=str(api_workspace.resolve()),
        memory_type=MemoryType.PROCEDURE,
        text="Run make check after queue sweep.",
    )
    cli_candidate = api_candidate.model_copy(
        update={
            "source_session_id": cli_session_id,
            "repo_id": str(cli_workspace.resolve()),
        }
    )
    SQLiteMemoryStore(api_database_path).upsert(api_candidate)
    SQLiteMemoryStore(cli_database_path).upsert(cli_candidate)

    api_response = RouteAdapter(create_app(api_database_path)).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{api_session_id}/memory/review-queue",
            body={"decision": "confirm", "operator": "alice", "reason": "queue sweep"},
        )
    )
    cli_result = execute(
        [
            "memory-review-queue",
            str(cli_session_id),
            "--decision",
            "confirm",
            "--operator",
            "alice",
            "--reason",
            "queue sweep",
            "--database",
            str(cli_database_path),
        ]
    )

    assert api_response.status_code == 200
    assert cli_result.command == "memory-review-queue"
    assert _summary(api_response.body) == _summary(cli_result.payload)


def _summary(payload: dict[str, object]) -> dict[str, object]:
    return {
        "status": payload["status"],
        "queue_sweep": payload["queue_sweep"],
        "queued_count": payload["queued_count"],
        "applied_count": payload["applied_count"],
        "skipped_count": payload["skipped_count"],
        "invalid_count": payload["invalid_count"],
        "results": [_normalize_result(result) for result in payload["results"]],
    }


def _normalize_result(result: object) -> dict[str, object]:
    assert isinstance(result, dict)
    normalized = dict(result)
    normalized.pop("database", None)
    normalized.pop("session_id", None)
    return normalized


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="queue-sweep-contract",
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
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )
