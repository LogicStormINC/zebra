from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.sessions import Session
from agent_storage import SQLiteEventStore, SQLiteMemoryStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_api_get_session_memory_returns_repo_scoped_records(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)
    _append_procedure_source_event(database_path, session_id)
    record = _memory_record(
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
    )
    SQLiteMemoryStore(database_path).upsert(record)

    response = create_app(database_path).get_session_memory(str(session_id))

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session_id),
        "repo_id": str(workspace.resolve()),
        "memories": [
            _memory_payload(
                record,
                source={
                    "kind": "tool",
                    "event_type": "tool_execution_completed",
                    "tool_name": "tests.run",
                    "source_event_start": 3,
                    "source_event_end": 3,
                    "captured_at": "2026-07-02T10:00:00+00:00",
                    "locator": "make check",
                    "cwd": ".",
                    "preset": "smoke",
                },
            )
        ],
    }


def test_api_get_session_memory_includes_last_review_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)
    _append_procedure_source_event(database_path, session_id)
    record = _memory_record(
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
        source_event_start=3,
        source_event_end=3,
    ).model_copy(update={"status": MemoryStatus.EXPIRED})
    SQLiteMemoryStore(database_path).upsert(record)
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

    response = create_app(database_path).get_session_memory(str(session_id))

    assert response.status_code == 200
    assert response.body["memories"] == [
        _memory_payload(
            record,
            source={
                    "kind": "tool",
                    "event_type": "tool_execution_completed",
                    "tool_name": "tests.run",
                    "source_event_start": 3,
                    "source_event_end": 3,
                    "captured_at": "2026-07-02T10:00:00+00:00",
                    "locator": "make check",
                    "cwd": ".",
                    "preset": "smoke",
            },
            last_review={
                "recorded_at": "2026-07-03T09:30:00+00:00",
                "previous_status": "confirmed",
                "status": "expired",
                "operator": "system",
                "reason": "stale after AGENTS.md refresh",
                "superseded_memory_ids": [],
                "duplicate_of_memory_id": None,
            },
        )
    ]


def test_api_get_session_memory_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session_memory(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_api_get_session_memory_requires_workspace_scope(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Missing workspace")
    )

    response = create_app(database_path).get_session_memory(str(session.session_id))

    assert response.status_code == 409
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "memory_unavailable",
        "reason": "session workspace_root is unavailable",
    }


def test_route_adapter_handles_session_memory(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)
    SQLiteMemoryStore(database_path).upsert(
        _memory_record(
            repo_id=str(workspace.resolve()),
            source_session_id=session_id,
            text="run make check after worker changes",
            source_event_start=3,
            source_event_end=3,
        )
    )
    _append_procedure_source_event(database_path, session_id)
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(RouteRequest(method="GET", path=f"/sessions/{session_id}/memory"))

    assert response.status_code == 200
    assert response.body["repo_id"] == str(workspace.resolve())
    assert len(response.body["memories"]) == 1


def test_api_get_session_memory_exposes_user_message_source_provenance(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)
    record = _memory_record(
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
        memory_type=MemoryType.PREFERENCE,
        text="Prefer concise CLI output.",
        source_event_start=3,
        source_event_end=3,
    )
    SQLiteMemoryStore(database_path).upsert(record)
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": "Preference: Prefer concise CLI output."},
            created_at=datetime(2026, 7, 2, 10, 5, tzinfo=UTC),
        )
    )

    response = create_app(database_path).get_session_memory(str(session_id))

    assert response.status_code == 200
    assert response.body["memories"] == [
        _memory_payload(
            record,
            source={
                "kind": "user_message",
                "event_type": "user_message_received",
                "source_event_start": 3,
                "source_event_end": 3,
                "captured_at": "2026-07-02T10:05:00+00:00",
            },
        )
    ]


def test_http_app_session_memory_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = _seed_ready_session(database_path, workspace)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(f"/sessions/{session_id}/memory")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def _seed_ready_session(database_path: Path, workspace_root: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Memory session",
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
    *,
    repo_id: str,
    source_session_id: SessionId,
    memory_type: MemoryType = MemoryType.PROCEDURE,
    text: str = "run tests.run check after command edits",
    source_event_start: int = 2,
    source_event_end: int = 2,
) -> MemoryRecord:
    created_at = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
    return MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000111")),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id=repo_id,
        source_session_id=source_session_id,
        source_event_start=source_event_start,
        source_event_end=source_event_end,
        created_at=created_at,
        updated_at=created_at,
    )


def _memory_payload(
    record: MemoryRecord,
    *,
    source: dict[str, object] | None = None,
    last_review: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        **record.model_dump(mode="json"),
        "source": source,
        "last_review": last_review,
    }


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


def _append_procedure_source_event(database_path: Path, session_id: SessionId) -> None:
    SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={
                "attempt_number": 1,
                "tool_name": "tests.run",
                "status": "executed",
                "output": "validated",
                "metadata": {
                    "command": ["make", "check"],
                    "cwd": ".",
                    "preset": "smoke",
                    "exit_code": 0,
                    "stderr": "",
                    "timed_out": False,
                },
            },
            created_at=datetime(2026, 7, 2, 10, 0, tzinfo=UTC),
        )
    )
