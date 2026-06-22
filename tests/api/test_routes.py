from pathlib import Path

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest


def test_route_adapter_handles_health(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "sessions.sqlite"))

    response = adapter.handle(RouteRequest(method="GET", path="/health"))

    assert response.status_code == 200
    assert response.body["status"] == "ok"


def test_route_adapter_handles_session_lookup(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Route session")
    )
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{session.session_id}")
    )

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert response.body["title"] == "Route session"


def test_route_adapter_returns_not_found_for_unknown_route(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "sessions.sqlite"))

    response = adapter.handle(RouteRequest(method="POST", path="/health"))

    assert response.status_code == 404
    assert response.body == {
        "method": "POST",
        "path": "/health",
        "status": "not_found",
    }


def test_route_adapter_handles_session_create(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "sessions.sqlite"))

    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/sessions",
            body={
                "prompt": "Create one session",
                "title": "Route create session",
            },
        )
    )

    assert response.status_code == 201
    assert response.body["executed"] is False
    assert response.body["title"] == "Route create session"


def test_route_adapter_handles_session_stream(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Route stream")
    )
    event = SQLiteEventStore(database_path).append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )
    adapter = RouteAdapter(create_app(database_path))

    response = adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{session.session_id}/stream")
    )
    events = response.body["events"]

    assert response.status_code == 200
    assert response.body["session_id"] == str(session.session_id)
    assert isinstance(events, list)
    assert events[0]["event_id"] == str(event.event_id)


def test_route_adapter_returns_not_found_for_invalid_session_subpath(tmp_path: Path) -> None:
    adapter = RouteAdapter(create_app(tmp_path / "sessions.sqlite"))

    response = adapter.handle(
        RouteRequest(
            method="GET",
            path="/sessions/00000000-0000-0000-0000-000000000001/unknown",
        )
    )

    assert response.status_code == 404
    assert response.body == {
        "method": "GET",
        "path": "/sessions/00000000-0000-0000-0000-000000000001/unknown",
        "status": "not_found",
    }
