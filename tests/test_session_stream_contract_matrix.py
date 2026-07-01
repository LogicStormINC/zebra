import json
from pathlib import Path

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_cli.cli import execute


def test_session_stream_contract_matrix_populated_replay_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Stream matrix")
    )
    event_store = SQLiteEventStore(database_path)
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": session.title, "user_input": "stream me"},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=2,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"reason": "done"},
        )
    )

    http_response = TestClient(create_http_app(database_path)).get(
        f"/sessions/{session.session_id}/stream"
    )
    cli_result = execute(["stream", str(session.session_id), "--database", str(database_path)])

    assert http_response.status_code == 200
    assert _normalize_http_stream(
        str(session.session_id),
        http_response.text,
    ) == _normalize_cli_stream(cli_result.payload)


def test_session_stream_contract_matrix_bootstrap_only_replay_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session = SQLiteProjectionStore(database_path).save_session(
        Session.create(title="Bootstrap only")
    )
    event_store = SQLiteEventStore(database_path)
    event_store.append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": session.title},
        )
    )

    http_response = TestClient(create_http_app(database_path)).get(
        f"/sessions/{session.session_id}/stream"
    )
    cli_result = execute(["stream", str(session.session_id), "--database", str(database_path)])

    assert http_response.status_code == 200
    assert _normalize_http_stream(
        str(session.session_id),
        http_response.text,
    ) == _normalize_cli_stream(cli_result.payload)


def test_session_stream_contract_matrix_missing_session_matches_across_api_and_cli(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    session_id = "00000000-0000-0000-0000-000000000001"

    http_response = TestClient(create_http_app(database_path)).get(f"/sessions/{session_id}/stream")
    cli_result = execute(["stream", session_id, "--database", str(database_path)])

    assert http_response.status_code == 404
    assert _normalize_http_not_found(
        http_response.json()
    ) == _normalize_cli_stream(cli_result.payload)


def _normalize_http_stream(session_id: str, raw_stream: str) -> dict[str, object]:
    chunks = [chunk for chunk in raw_stream.strip().split("\n\n") if chunk]
    events: list[dict[str, object]] = []
    for chunk in chunks:
        data_lines = [line for line in chunk.splitlines() if line.startswith("data: ")]
        assert len(data_lines) == 1
        events.append(json.loads(data_lines[0].removeprefix("data: ")))
    return {
        "session_id": session_id,
        "status": "ok",
        "events": events,
    }


def _normalize_http_not_found(payload: dict[str, object]) -> dict[str, object]:
    return {
        "session_id": payload["session_id"],
        "status": "not_found",
    }


def _normalize_cli_stream(payload: dict[str, object]) -> dict[str, object]:
    if payload.get("status") == "not_found":
        return {
            "session_id": payload["session_id"],
            "status": "not_found",
        }
    return {
        "session_id": payload["session_id"],
        "status": "ok",
        "events": payload["events"],
    }
