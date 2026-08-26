from pathlib import Path

import pytest
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SessionEventSequenceConflictError, SQLiteProjectionStore
from fastapi.testclient import TestClient
from http_app_support import (
    _finish_first_turn,
    _seed_ready_session,
    _settings,
)
from zebra_agent_api import create_http_app
from zebra_agent_api.session_message_submission import append_session_message_event


def test_http_app_appends_session_message(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database_path, workspace_root=tmp_path)
    _finish_first_turn(database_path, session_id)
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
        "sequence": 5,
        "status": "ready",
        "current_sequence": 5,
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


def test_http_app_message_append_rejects_invalid_session_id(tmp_path: Path) -> None:
    client = TestClient(create_http_app(tmp_path / "sessions.sqlite"))

    response = client.post(
        "/sessions/not-a-valid-uuid/messages",
        json={"content": "Continue."},
    )

    assert response.status_code == 400
    assert response.json() == {
        "session_id": "not-a-valid-uuid",
        "status": "invalid_request",
        "reason": "session_id must be a valid UUID",
    }


def test_message_append_maps_only_sequence_races_to_conflict() -> None:
    class _Store:
        def __init__(self, error: ValueError) -> None:
            self.error = error

        def append(self, event: object) -> object:
            raise self.error

    assert (
        append_session_message_event(
            _Store(SessionEventSequenceConflictError("lost sequence CAS")),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )
        is None
    )
    with pytest.raises(ValueError, match="event id replayed"):
        append_session_message_event(
            _Store(ValueError("event id replayed with conflicting content")),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )
