from pathlib import Path

from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_config import ModelSettings, ZebraAgentSettings


def test_api_health_returns_service_status(tmp_path: Path) -> None:
    app = create_app(tmp_path / "sessions.sqlite")

    response = app.health()

    assert response.status_code == 200
    assert response.body == {
        "service": "zebra-agent-api",
        "status": "ok",
    }


def test_api_create_app_uses_settings_database_by_default(tmp_path: Path) -> None:
    database_path = tmp_path / "configured.sqlite"
    app = create_app(settings=_settings(database_path))

    assert app.database_path == database_path


def test_api_create_app_database_path_overrides_settings(tmp_path: Path) -> None:
    configured_path = tmp_path / "configured.sqlite"
    explicit_path = tmp_path / "explicit.sqlite"
    app = create_app(explicit_path, settings=_settings(configured_path))

    assert app.database_path == explicit_path


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


def _settings(database_path: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )
