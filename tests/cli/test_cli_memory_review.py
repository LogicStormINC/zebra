from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_memory_review_confirms_candidate(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id, record = _seed_completed_candidate(database_path, tmp_path / "workspace")

    result = execute(
        [
            "memory-review",
            session_id,
            str(record.memory_id),
            "--decision",
            "confirm",
            "--database",
            str(database_path),
        ]
    )

    updated = SQLiteMemoryStore(database_path).get(record.memory_id)

    assert result.command == "memory-review"
    assert result.payload["decision"] == "confirm"
    assert result.payload["memory_status"] == "confirmed"
    assert result.payload["superseded_memory_ids"] == []
    assert result.payload["duplicate_of_memory_id"] is None
    assert updated is not None
    assert updated.status is MemoryStatus.CONFIRMED


def test_cli_memory_review_reports_invalid_state_for_non_candidate(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id, record = _seed_completed_candidate(database_path, tmp_path / "workspace")
    SQLiteMemoryStore(database_path).upsert(
        record.model_copy(update={"status": MemoryStatus.CONFIRMED})
    )

    result = execute(
        [
            "memory-review",
            session_id,
            str(record.memory_id),
            "--decision",
            "expire",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload["status"] == "invalid_state"
    assert "candidate memory" in str(result.payload["reason"])


def test_cli_memory_review_reports_missing_memory(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id, _ = _seed_completed_candidate(database_path, tmp_path / "workspace")

    result = execute(
        [
            "memory-review",
            session_id,
            "00000000-0000-0000-0000-000000000999",
            "--decision",
            "confirm",
            "--database",
            str(database_path),
        ]
    )

    assert result.payload == {
        "session_id": session_id,
        "memory_id": "00000000-0000-0000-0000-000000000999",
        "database": str(database_path),
        "status": "not_found",
    }


def test_cli_memory_review_supersedes_prior_confirmed_memory(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id, record = _seed_completed_candidate(database_path, tmp_path / "workspace")
    prior = record.model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000135")),
            "status": MemoryStatus.CONFIRMED,
            "text": "run uv run pytest before push",
        }
    )
    SQLiteMemoryStore(database_path).upsert(prior)

    result = execute(
        [
            "memory-review",
            session_id,
            str(record.memory_id),
            "--decision",
            "confirm",
            "--database",
            str(database_path),
        ]
    )

    superseded = SQLiteMemoryStore(database_path).get(prior.memory_id)

    assert result.payload["superseded_memory_ids"] == [str(prior.memory_id)]
    assert result.payload["duplicate_of_memory_id"] is None
    assert superseded is not None
    assert superseded.status is MemoryStatus.SUPERSEDED
    assert superseded.superseded_by == record.memory_id


def test_cli_memory_review_keeps_prior_confirmed_preference(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id, record = _seed_completed_candidate(database_path, tmp_path / "workspace")
    preference_record = record.model_copy(
        update={
            "memory_type": MemoryType.PREFERENCE,
            "text": "Prefer concise CLI output.",
        }
    )
    SQLiteMemoryStore(database_path).upsert(preference_record)
    prior = preference_record.model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000137")),
            "status": MemoryStatus.CONFIRMED,
            "text": "Prefer focused test runs first.",
        }
    )
    SQLiteMemoryStore(database_path).upsert(prior)

    result = execute(
        [
            "memory-review",
            session_id,
            str(preference_record.memory_id),
            "--decision",
            "confirm",
            "--database",
            str(database_path),
        ]
    )

    persisted_prior = SQLiteMemoryStore(database_path).get(prior.memory_id)

    assert result.payload["superseded_memory_ids"] == []
    assert result.payload["duplicate_of_memory_id"] is None
    assert persisted_prior is not None
    assert persisted_prior.status is MemoryStatus.CONFIRMED
    assert persisted_prior.superseded_by is None


def test_cli_memory_review_expires_duplicate_candidate_against_confirmed_match(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id, record = _seed_completed_candidate(database_path, tmp_path / "workspace")
    prior = record.model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000139")),
            "status": MemoryStatus.CONFIRMED,
            "text": "run   make check before push",
        }
    )
    SQLiteMemoryStore(database_path).upsert(prior)

    result = execute(
        [
            "memory-review",
            session_id,
            str(record.memory_id),
            "--decision",
            "confirm",
            "--database",
            str(database_path),
        ]
    )

    updated = SQLiteMemoryStore(database_path).get(record.memory_id)

    assert result.payload["memory_status"] == "expired"
    assert result.payload["superseded_memory_ids"] == []
    assert result.payload["duplicate_of_memory_id"] == str(prior.memory_id)
    assert updated is not None
    assert updated.status is MemoryStatus.EXPIRED


def _seed_completed_candidate(
    database_path: Path,
    workspace_root: Path,
) -> tuple[str, MemoryRecord]:
    workspace_root.mkdir()
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI memory review",
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
            created_at=datetime(2026, 7, 2, 11, 0, tzinfo=UTC),
        )
    )
    SQLiteProjectionStore(database_path).save_session(completed)
    record = MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000132")),
        memory_type=MemoryType.PROCEDURE,
        text="run make check before push",
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace_root.resolve()),
        source_session_id=completed.session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=datetime(2026, 7, 2, 11, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 2, 11, 0, tzinfo=UTC),
    )
    SQLiteMemoryStore(database_path).upsert(record)
    return str(completed.session_id), record
