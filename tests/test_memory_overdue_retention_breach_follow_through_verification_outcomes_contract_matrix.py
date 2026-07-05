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


def test_follow_through_verification_outcomes_contract_matrix_matches_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    api_session_id = str(session_id)
    SQLiteMemoryStore(database_path).upsert(
        _memory_record(
            memory_id="00000000-0000-0000-0000-000000001111",
            session_id=session_id,
            visibility=MemoryVisibility.REPO,
            memory_type=MemoryType.PROCEDURE,
            text="Oldest pending repo memory.",
            status=MemoryStatus.CANDIDATE,
            repo_id=str(workspace.resolve()),
            timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
    )

    api_response = RouteAdapter(create_app(database_path)).handle(
        RouteRequest(
            method="POST",
            path=(
                f"/sessions/{api_session_id}/"
                "memory-overdue-retention-breach-follow-through-verification-outcomes"
            ),
            body={"as_of": "2026-08-20T06:00:00+00:00"},
        )
    )
    cli_result = execute(
        [
            "memory-overdue-retention-breach-follow-through-verification-outcomes",
            api_session_id,
            "--as-of",
            "2026-08-20T06:00:00+00:00",
            "--database",
            str(database_path),
        ]
    )

    assert api_response.status_code == 200
    assert (
        cli_result.command
        == "memory-overdue-retention-breach-follow-through-verification-outcomes"
    )
    assert _contract_summary(api_response.body) == _contract_summary(cli_result.payload)


def _contract_summary(payload: dict[str, object]) -> dict[str, object]:
    return {
        "status": payload["status"],
        "scope_count": payload["scope_count"],
        "overdue_scope_count": payload["overdue_scope_count"],
        "overdue_retention_breach_follow_through_verification_outcome_counts": payload[
            "overdue_retention_breach_follow_through_verification_outcome_counts"
        ],
        "highest_priority_overdue_retention_breach_follow_through_verification_outcome": (
            payload[
                "highest_priority_overdue_retention_breach_follow_through_verification_outcome"
            ]
        ),
        (
            "highest_priority_overdue_retention_breach_follow_through_"
            "verification_outcome_scope_kind"
        ): (
            payload[
                "highest_priority_overdue_retention_breach_follow_through_verification_outcome_scope_kind"
            ]
        ),
        "highest_priority_overdue_retention_breach_follow_through_verification_outcome_memory_id": (
            payload[
                "highest_priority_overdue_retention_breach_follow_through_verification_outcome_memory_id"
            ]
        ),
        "scopes": payload["scopes"],
    }


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory overdue retention breach follow-through verification outcomes matrix",
            user_input="Inspect overdue retention breach follow-through verification outcomes.",
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
