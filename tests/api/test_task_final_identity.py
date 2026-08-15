from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.task_final_identity import final_message_identity


def test_task_final_identity_uses_terminal_explicit_final_after_continued_work(
    tmp_path: Path,
) -> None:
    database = tmp_path / "task-final-identity.sqlite"
    adapter = RouteAdapter(create_app(database))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={"title": "Real provider shape", "prompt": "Inspect", "workspace": str(tmp_path)},
        )
    )
    task_id = str(created.body["task_id"])
    segment_id = SessionId(UUID(task_id))
    session = SQLiteProjectionStore(database).get_session(segment_id)
    assert session is not None
    first_final = SessionEvent.create(
        session_id=segment_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload={
            "assistant_message": "superseded final",
            "response_stage": "final",
            "tool_call_count": 0,
        },
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    tool = SessionEvent.create(
        session_id=segment_id,
        sequence=session.current_sequence + 2,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "files.read",
            "tool_call_id": "continued-work",
            "status": "executed",
            "output": "done",
            "metadata": {},
        },
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    terminal_final = SessionEvent.create(
        session_id=segment_id,
        sequence=session.current_sequence + 3,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload={
            "assistant_message": "terminal final",
            "response_stage": "final",
            "tool_call_count": 0,
        },
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    completed = SessionEvent.create(
        session_id=segment_id,
        sequence=session.current_sequence + 4,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"summary": "done"},
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    event_store = SQLiteEventStore(database)
    for event in (first_final, tool, terminal_final, completed):
        event_store.append(event)

    conversation = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}/conversation"))

    assert [
        item["content"]
        for item in conversation.body["items"]
        if item["role"] == "final_response"
    ] == ["terminal final"]
    assert final_message_identity(database, task_id) == {
        "message_id": f"final:{terminal_final.event_id}",
        "cursor": 5,
    }
