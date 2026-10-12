"""Reject future Task cursors before SSE headers, preserving valid replay suffixes."""

from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore
from agent_storage.postgres.task_io import current_task_io_deadline
from fastapi.testclient import TestClient
from zebra_agent_api.http import create_http_app

from tests.api.test_live_session_streaming import _seed_session


def test_task_cursor_preflight_is_body_free_grant_bounded_and_precedes_sse(tmp_path, monkeypatch):
    database, session_id, revision = _seed_session(tmp_path)
    events = SQLiteEventStore(database)
    events.append(SessionEvent.create(
        session_id=session_id, sequence=revision + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED, actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    ))
    revision += 1
    terminal = events.append(SessionEvent.create(
        session_id=session_id, sequence=revision + 1,
        event_type=EventType.SESSION_COMPLETED, actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "summary": "done", "metadata": {}},
    ))
    SQLiteProjectionStore(database).save_session(rebuild_session(events.list_for_session(session_id)))
    task = SQLiteAgentTaskStore(database).ensure_for_session(session_id)
    header = SQLiteAgentTaskStore.read_task_header
    reads = []

    def bounded(store, task_id):
        assert current_task_io_deadline() is not None
        result = header(store, task_id)
        reads.append(result)
        return result

    monkeypatch.setattr(SQLiteAgentTaskStore, "read_task_header", bounded)
    client = TestClient(create_http_app(database))
    response = client.get(f"/tasks/{task.task_id}/stream?after_sequence=999")
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "invalid_request", "reason": "after_sequence exceeds Task highwater",
    }
    assert reads[-1].current_sequence == terminal.sequence

    response = client.get(f"/tasks/{task.task_id}/stream?after_sequence={revision}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.startswith(f"id: {terminal.sequence}\nevent: task_event\n")
    assert response.text.count("session_completed") == 1

    # Session legacy cursors retain their existing empty terminal suffix behavior.
    response = client.get(f"/sessions/{session_id}/stream?after_sequence=999")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == ""
