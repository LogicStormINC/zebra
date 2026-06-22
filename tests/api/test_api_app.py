from pathlib import Path

from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteProjectionStore
from zebra_agent_api.app import create_app


def test_api_health_returns_service_status(tmp_path: Path) -> None:
    app = create_app(tmp_path / "sessions.sqlite")

    response = app.health()

    assert response.status_code == 200
    assert response.body == {
        "service": "zebra-agent-api",
        "status": "ok",
    }


def test_api_get_session_returns_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="API session")
    )

    response = create_app(database_path).get_session(str(session.session_id))

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session.session_id),
        "title": "API session",
        "status": SessionStatus.CREATED.value,
        "current_sequence": 0,
    }


def test_api_get_session_returns_not_found(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").get_session(
        "00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.body == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "status": "not_found",
    }
