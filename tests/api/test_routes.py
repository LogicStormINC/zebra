from pathlib import Path

from agent_core.domain.sessions import Session
from agent_storage import SQLiteProjectionStore
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
