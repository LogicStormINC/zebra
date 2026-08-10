from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_event_id
from agent_integrations.ag_ui import AgUiCursor
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
    sqlite_control_plane_stores,
)
from fastapi.testclient import TestClient
from zebra_agent_api.ag_ui_stream import AgUiStreamContext, prepare_agui_stream, tail_agui_events
from zebra_agent_api.http import create_http_app

NOW = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)


def test_agui_stream_replays_official_events_with_exact_cursor_ids(tmp_path: Path) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    event_store = SQLiteEventStore(database_path)
    _append(event_store, session_id, next_sequence, EventType.TASK_PREPARED, {"title": "Task"})
    _append(
        event_store,
        session_id,
        next_sequence + 1,
        EventType.RUNTIME_PROVISIONED,
        {"runtime_id": "ignored"},
    )
    delta = _append(
        event_store,
        session_id,
        next_sequence + 2,
        EventType.MODEL_RESPONSE_DELTA,
        {"model_call_id": "model-1", "content_delta": "hello"},
    )
    _append(
        event_store,
        session_id,
        next_sequence + 3,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "model-1", "assistant_message": "hello"},
    )
    _append(event_store, session_id, next_sequence + 4, EventType.SESSION_COMPLETED, {})

    client = TestClient(
        create_http_app(database_path, stores=sqlite_control_plane_stores(database_path))
    )
    response = client.get(_stream_path(session_id, "run-1"))

    assert response.status_code == 200
    assert "RUN_STARTED" in response.text
    assert "TEXT_MESSAGE_CONTENT" in response.text
    assert "RUN_FINISHED" in response.text
    cursor = _cursor_for_sequence(response.text, delta.sequence)
    assert cursor is not None

    tail = client.get(f"{_stream_path(session_id, 'run-1')}?cursor={cursor}")

    assert tail.status_code == 200
    assert "RUN_STARTED" not in tail.text
    assert "TEXT_MESSAGE_END" in tail.text
    assert "RUN_FINISHED" in tail.text


def test_agui_stream_rejects_malformed_or_cross_run_cursor(tmp_path: Path) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    event_store = SQLiteEventStore(database_path)
    event = _append(
        event_store,
        session_id,
        next_sequence,
        EventType.TASK_PREPARED,
        {"title": "Task"},
    )
    stores = sqlite_control_plane_stores(database_path)
    cursor = AgUiCursor(
        thread_id=str(session_id),
        run_id="other-run",
        sequence=event.sequence,
        event_id=str(event.event_id),
    ).encode()
    client = TestClient(create_http_app(database_path, stores=stores))

    malformed = client.get(f"{_stream_path(session_id, 'run-1')}?cursor=bad")
    cross_run = client.get(f"{_stream_path(session_id, 'run-1')}?cursor={cursor}")

    assert malformed.status_code == 400
    assert malformed.json()["code"] == "invalid_cursor"
    assert cross_run.status_code == 400
    assert cross_run.json()["code"] == "invalid_cursor"


def test_agui_stream_live_tail_reads_new_durable_event_without_command_retry(
    tmp_path: Path,
) -> None:
    database_path, session_id, next_sequence = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(database_path)
    context = prepare_agui_stream(
        stores,
        _stream_path(session_id, "run-live"),
        {},
    )
    assert isinstance(context, AgUiStreamContext)
    request = _FakeRequest()
    stream = tail_agui_events(context, request)

    async def consume() -> tuple[str, str, str, str, str]:
        first = await anext(stream)
        initial_state = await anext(stream)
        _append(
            SQLiteEventStore(database_path),
            session_id,
            next_sequence,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "live-model", "assistant_message": "live"},
        )
        live_start = await asyncio.wait_for(anext(stream), timeout=1)
        live_content = await asyncio.wait_for(anext(stream), timeout=1)
        live_end = await asyncio.wait_for(anext(stream), timeout=1)
        request.disconnected = True
        return first, initial_state, live_start, live_content, live_end

    first, initial_state, live_start, live_content, live_end = asyncio.run(consume())

    assert "RUN_STARTED" in first or "STATE_SNAPSHOT" in first
    assert "STATE_SNAPSHOT" in initial_state
    assert "TEXT_MESSAGE_START" in live_start
    assert "TEXT_MESSAGE_CONTENT" in live_content
    assert "TEXT_MESSAGE_END" in live_end


class _FakeRequest:
    disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def _stream_path(session_id: SessionId, run_id: str) -> str:
    return f"/agui/threads/{session_id}/runs/{run_id}/stream"


def _cursor_for_sequence(text: str, sequence: int) -> str | None:
    blocks = text.split("\n\n")
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 2 or not lines[0].startswith("id: "):
            continue
        try:
            cursor = AgUiCursor.decode(lines[0].removeprefix("id: "))
        except ValueError:
            continue
        if cursor.sequence == sequence:
            return lines[0].removeprefix("id: ")
    return None


def _append(
    store: SQLiteEventStore,
    session_id: SessionId,
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
) -> SessionEvent:
    event = SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        actor=EventActor.HARNESS,
        created_at=NOW,
    )
    store.append(event)
    return event


def _seed_ready_session(tmp_path: Path) -> tuple[Path, SessionId, int]:
    database_path = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="AG-UI stream",
            user_input="Replay the durable stream.",
            workspace_root=tmp_path.resolve(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SQLiteWorkspaceProjectionStore(database_path).save_workspace(
        rebuild_workspace(list(bootstrap.events))
    )
    return database_path, bootstrap.session.session_id, bootstrap.session.current_sequence + 1
