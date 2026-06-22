import json
from pathlib import Path

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session
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
            payload={"prompt": "stream me"},
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
