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


def test_memory_follow_up_windows_contract_matrix_matches_across_api_and_cli(
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

    api_pending = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000631",
        session_id=api_session_id,
        visibility=MemoryVisibility.REPO,
        memory_type=MemoryType.PROCEDURE,
        text="Oldest pending repo memory.",
        status=MemoryStatus.CANDIDATE,
        repo_id=str(api_workspace.resolve()),
        timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
    )
    cli_pending = _memory_record(
        memory_id="00000000-0000-0000-0000-000000000632",
        session_id=cli_session_id,
        visibility=MemoryVisibility.REPO,
        memory_type=MemoryType.PROCEDURE,
        text="Oldest pending repo memory.",
        status=MemoryStatus.CANDIDATE,
        repo_id=str(cli_workspace.resolve()),
        timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
    )
    SQLiteMemoryStore(api_database_path).upsert(api_pending)
    SQLiteMemoryStore(cli_database_path).upsert(cli_pending)

    http_response = TestClient(create_http_app(api_database_path)).post(
        f"/sessions/{api_session_id}/memory-follow-up-windows",
        json={"as_of": "2026-07-09T00:00:00+00:00"},
    )
    cli_result = execute(
        [
            "memory-follow-up-windows",
            str(cli_session_id),
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
        "follow_up_window_counts": payload["follow_up_window_counts"],
        "highest_priority_follow_up_window": payload["highest_priority_follow_up_window"],
        "highest_priority_follow_up_priority": payload[
            "highest_priority_follow_up_priority"
        ],
        "highest_priority_follow_up_scope_kind": payload[
            "highest_priority_follow_up_scope_kind"
        ],
    }


def _normalize_cli(payload: dict[str, object]) -> dict[str, object]:
    return {
        "reference_at": payload["reference_at"],
        "scope_count": payload["scope_count"],
        "follow_up_window_counts": payload["follow_up_window_counts"],
        "highest_priority_follow_up_window": payload["highest_priority_follow_up_window"],
        "highest_priority_follow_up_priority": payload[
            "highest_priority_follow_up_priority"
        ],
        "highest_priority_follow_up_scope_kind": payload[
            "highest_priority_follow_up_scope_kind"
        ],
    }


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory follow up windows matrix",
            user_input="Inspect follow up windows.",
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
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=MemoryId(UUID(memory_id)),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=status,
        visibility=visibility,
        repo_id=repo_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=timestamp,
        updated_at=timestamp,
    )
