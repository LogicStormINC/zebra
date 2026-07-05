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
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_api_confirm_session_memory_records_review(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    record = _candidate_record(session_id, str(workspace.resolve()))
    SQLiteMemoryStore(database_path).upsert(record)

    response = create_app(database_path).confirm_session_memory(
        str(session_id),
        str(record.memory_id),
        {"operator": "alice", "reason": "validated locally"},
    )

    updated = SQLiteMemoryStore(database_path).get(record.memory_id)
    events = SQLiteEventStore(database_path).list_for_session(session_id)

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session_id),
        "memory_id": str(record.memory_id),
        "decision": "confirm",
        "event_type": EventType.MEMORY_REVIEW_RECORDED.value,
        "sequence": 4,
        "status": "completed",
        "memory_status": "confirmed",
        "superseded_memory_ids": [],
        "duplicate_of_memory_id": None,
    }
    assert updated is not None
    assert updated.status is MemoryStatus.CONFIRMED
    assert events[-1].payload["status"] == "confirmed"


def test_api_expire_session_memory_records_review(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    record = _candidate_record(session_id, str(workspace.resolve()))
    SQLiteMemoryStore(database_path).upsert(record)

    response = create_app(database_path).expire_session_memory(
        str(session_id),
        str(record.memory_id),
        {},
    )

    assert response.status_code == 200
    assert response.body["decision"] == "expire"
    assert response.body["memory_status"] == "expired"
    assert response.body["duplicate_of_memory_id"] is None


def test_api_memory_review_rejects_non_candidate_record(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    record = _candidate_record(
        session_id,
        str(workspace.resolve()),
    ).model_copy(update={"status": MemoryStatus.CONFIRMED})
    SQLiteMemoryStore(database_path).upsert(record)

    response = create_app(database_path).confirm_session_memory(
        str(session_id),
        str(record.memory_id),
        {},
    )

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session_id),
        "status": "invalid_state",
        "reason": "memory review requires a candidate memory",
    }


def test_api_confirm_session_memory_supersedes_prior_confirmed_memory(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    record = _candidate_record(session_id, str(workspace.resolve()))
    prior = record.model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000134")),
            "status": MemoryStatus.CONFIRMED,
            "text": "run uv run pytest before push",
        }
    )
    SQLiteMemoryStore(database_path).upsert(record)
    SQLiteMemoryStore(database_path).upsert(prior)

    response = create_app(database_path).confirm_session_memory(
        str(session_id),
        str(record.memory_id),
        {"operator": "alice", "reason": "validated locally"},
    )

    superseded = SQLiteMemoryStore(database_path).get(prior.memory_id)

    assert response.status_code == 200
    assert response.body["superseded_memory_ids"] == [str(prior.memory_id)]
    assert response.body["duplicate_of_memory_id"] is None
    assert superseded is not None
    assert superseded.status is MemoryStatus.SUPERSEDED
    assert superseded.superseded_by == record.memory_id


def test_api_confirm_preference_memory_keeps_prior_confirmed_preference(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    record = _candidate_record(session_id, str(workspace.resolve())).model_copy(
        update={
            "memory_type": MemoryType.PREFERENCE,
            "text": "Prefer concise CLI output.",
        }
    )
    prior = record.model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000136")),
            "status": MemoryStatus.CONFIRMED,
            "text": "Prefer focused test runs first.",
        }
    )
    SQLiteMemoryStore(database_path).upsert(record)
    SQLiteMemoryStore(database_path).upsert(prior)

    response = create_app(database_path).confirm_session_memory(
        str(session_id),
        str(record.memory_id),
        {"operator": "alice", "reason": "captured explicit preference"},
    )

    persisted_prior = SQLiteMemoryStore(database_path).get(prior.memory_id)

    assert response.status_code == 200
    assert response.body["superseded_memory_ids"] == []
    assert response.body["duplicate_of_memory_id"] is None
    assert persisted_prior is not None
    assert persisted_prior.status is MemoryStatus.CONFIRMED
    assert persisted_prior.superseded_by is None


def test_api_confirm_duplicate_memory_expires_candidate_against_confirmed_match(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    record = _candidate_record(session_id, str(workspace.resolve()))
    prior = record.model_copy(
        update={
            "memory_id": MemoryId(UUID("00000000-0000-0000-0000-000000000138")),
            "status": MemoryStatus.CONFIRMED,
            "text": "run   make check before push",
        }
    )
    SQLiteMemoryStore(database_path).upsert(record)
    SQLiteMemoryStore(database_path).upsert(prior)

    response = create_app(database_path).confirm_session_memory(
        str(session_id),
        str(record.memory_id),
        {"operator": "alice", "reason": "duplicate verified command"},
    )

    updated = SQLiteMemoryStore(database_path).get(record.memory_id)

    assert response.status_code == 200
    assert response.body["memory_status"] == "expired"
    assert response.body["superseded_memory_ids"] == []
    assert response.body["duplicate_of_memory_id"] == str(prior.memory_id)
    assert updated is not None
    assert updated.status is MemoryStatus.EXPIRED


def test_route_adapter_handles_memory_confirm(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    record = _candidate_record(session_id, str(workspace.resolve()))
    SQLiteMemoryStore(database_path).upsert(record)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/memory/{record.memory_id}/confirm",
            body={"operator": "alice", "reason": "validated locally"},
        )
    )

    assert response.status_code == 200
    assert response.body["memory_status"] == "confirmed"


def test_http_app_memory_review_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_completed_session(database_path, workspace)
    record = _candidate_record(session_id, str(workspace.resolve()))
    SQLiteMemoryStore(database_path).upsert(record)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(f"/sessions/{session_id}/memory/{record.memory_id}/confirm")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def _seed_completed_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory review",
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
    return completed.session_id


def _candidate_record(session_id: SessionId, repo_id: str) -> MemoryRecord:
    created_at = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000131")),
        memory_type=MemoryType.PROCEDURE,
        text="run make check before push",
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id=repo_id,
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
        created_at=created_at,
        updated_at=created_at,
    )


def _settings(auth_token: str | None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )
