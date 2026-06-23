import json
from datetime import UTC, datetime
from pathlib import Path

import zebra_agent_api.app as api_app_module
import zebra_agent_worker.execution as worker_execution_module
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_http_app_serves_health(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "zebra-agent-api",
        "status": "ok",
    }


def test_http_app_serves_session_lookup(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="HTTP session")
    )
    client = TestClient(create_http_app(database_path))

    response = client.get(f"/sessions/{session.session_id}")

    assert response.status_code == 200
    assert response.json()["session_id"] == str(session.session_id)
    assert response.json()["title"] == "HTTP session"


def test_http_app_returns_not_found_for_unknown_path(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {
        "method": "GET",
        "path": "/missing",
        "status": "not_found",
    }


def test_http_app_returns_not_found_for_unsupported_method(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post("/health")

    assert response.status_code == 404
    assert response.json() == {
        "method": "POST",
        "path": "/health",
        "status": "not_found",
    }


def test_http_app_streams_session_events_as_sse(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="HTTP stream")
    )
    event_store = SQLiteEventStore(database_path)
    created = event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )
    prepared = event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": session.title,
                "user_input": "stream me",
            },
        )
    )
    client = TestClient(create_http_app(database_path))

    response = client.get(f"/sessions/{session.session_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    chunks = [chunk for chunk in response.text.strip().split("\n\n") if chunk]
    assert len(chunks) == 2
    assert f"id: {created.event_id}" in chunks[0]
    assert f"id: {prepared.event_id}" in chunks[1]
    assert "event: session_event" in chunks[0]
    data_lines = [line for line in chunks[0].splitlines() if line.startswith("data: ")]
    first_event = json.loads(data_lines[0].removeprefix("data: "))
    assert first_event["sequence"] == 0
    assert first_event["event_type"] == EventType.SESSION_CREATED.value


def test_http_app_stream_missing_session_returns_not_found(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.get("/sessions/00000000-0000-0000-0000-000000000001/stream")

    assert response.status_code == 404
    assert response.json() == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_http_app_creates_session(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions",
        json={
            "prompt": "Inspect the workspace",
            "title": "HTTP create session",
        },
    )

    assert response.status_code == 201
    assert response.json()["executed"] is False
    assert response.json()["title"] == "HTTP create session"


def test_http_app_executes_session_create(tmp_path: Path, monkeypatch) -> None:
    from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
    from agent_core.domain.identifiers import new_message_id
    from agent_core.domain.messages import MessageRole, SessionMessage
    from agent_core.domain.modeling import ModelCompletion

    def fake_build_model_gateway(settings: ZebraAgentSettings):
        del settings
        return ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="HTTP execution complete.",
                            created_at=_created_at(),
                        )
                    )
                ),
            )
        )

    monkeypatch.setattr(api_app_module, "build_model_gateway", fake_build_model_gateway)
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite", settings=_settings("secret")))

    response = client.post(
        "/sessions",
        headers={"Authorization": "Bearer secret"},
        json={
            "prompt": "Inspect the workspace",
            "title": "HTTP execute session",
            "workspace": str(tmp_path),
            "execute": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["executed"] is True
    assert response.json()["assistant_message"] == "HTTP execution complete."


def test_http_app_executes_session_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", _fake_resume_gateway)
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(
        f"/sessions/{session_id}/resume",
        headers={"Authorization": "Bearer secret"},
        json={"worker_id": "api-worker", "lease_ttl_seconds": 45},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session_id,
        "executed": True,
        "worker_id": "api-worker",
        "status": "completed",
        "current_sequence": 6,
        "assistant_message": "HTTP resume complete.",
        "trace": [
            {
                "attempt_number": 1,
                "assistant_message": "HTTP resume complete.",
                "tools": [],
            }
        ],
    }


def test_http_app_appends_session_message(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "Please continue from the last checkpoint."},
    )

    assert response.status_code == 201
    assert response.json() == {
        "session_id": session_id,
        "appended": True,
        "content": "Please continue from the last checkpoint.",
        "sequence": 3,
        "status": "ready",
        "current_sequence": 3,
    }


def test_http_app_message_append_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "Continue."},
    )

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def test_http_app_message_append_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(
        f"/sessions/{session_id}/messages",
        json={"content": "   "},
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "content must be a non-blank string",
    }


def test_http_app_message_append_missing_session_returns_not_found(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions/00000000-0000-0000-0000-000000000001/messages",
        json={"content": "Continue."},
    )

    assert response.status_code == 404
    assert response.json() == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_http_app_message_append_terminal_session_returns_conflict(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Terminal message").model_copy(
            update={"status": SessionStatus.COMPLETED}
        )
    )
    client = TestClient(create_http_app(database_path))

    response = client.post(
        f"/sessions/{session.session_id}/messages",
        json={"content": "Try again."},
    )

    assert response.status_code == 409
    assert response.json() == {
        "session_id": str(session.session_id),
        "status": "not_appendable",
        "reason": "cannot_append_to_terminal_session",
    }


def test_http_app_resume_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.post(f"/sessions/{session_id}/resume", json={})

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def test_http_app_resume_rejects_invalid_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    response = client.post(
        f"/sessions/{session_id}/resume",
        json={"lease_ttl_seconds": 0},
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "lease_ttl_seconds must be greater than zero",
    }


def test_http_app_resume_missing_session_returns_not_found(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions/00000000-0000-0000-0000-000000000001/resume",
        json={},
    )

    assert response.status_code == 404
    assert response.json() == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }


def test_http_app_resume_terminal_session_returns_conflict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(worker_execution_module, "build_model_gateway", _fake_resume_gateway)
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    client = TestClient(create_http_app(database_path))

    first = client.post(f"/sessions/{session_id}/resume", json={})
    second = client.post(f"/sessions/{session_id}/resume", json={})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {
        "session_id": session_id,
        "status": "not_resumable",
        "reason": "cannot_resume_terminal_session",
    }


def test_http_app_rejects_invalid_json_body(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions",
        content="{invalid",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "invalid_request",
        "reason": "request body must be valid JSON",
    }


def test_http_app_health_remains_public_with_auth_enabled(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite", settings=_settings("secret")))

    response = client.get("/health")

    assert response.status_code == 200


def test_http_app_session_routes_require_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Auth session")
    )
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(f"/sessions/{session.session_id}")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def test_http_app_session_routes_reject_invalid_bearer_token(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Auth session")
    )
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(
        f"/sessions/{session.session_id}",
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
    }


def test_http_app_session_routes_allow_valid_bearer_token(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Auth session")
    )
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(
        f"/sessions/{session.session_id}",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == str(session.session_id)


def test_http_app_stream_route_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Auth stream")
    )
    client = TestClient(create_http_app(database_path, settings=_settings("secret")))

    response = client.get(f"/sessions/{session.session_id}/stream")

    assert response.status_code == 401
    assert response.json() == {
        "status": "unauthorized",
        "reason": "missing_or_invalid_bearer_token",
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


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 6, 22, 13, 25, tzinfo=UTC)


def _seed_ready_session(database_path: Path, *, workspace_root: Path) -> str:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="HTTP queued session",
            user_input="Summarize the workspace",
            workspace_root=workspace_root,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    return str(bootstrap.session.session_id)


def _fake_resume_gateway(_settings: ZebraAgentSettings) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="HTTP resume complete.",
                        created_at=datetime(2026, 6, 22, 13, 25, tzinfo=UTC),
                    )
                )
            ),
        )
    )
