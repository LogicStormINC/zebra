from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app

NOW = datetime(2026, 7, 27, tzinfo=UTC)


def test_stable_task_conversation_keeps_two_turns_after_terminal_follow_up(
    tmp_path: Path,
) -> None:
    database = tmp_path / "task-conversation.sqlite"
    adapter = RouteAdapter(create_app(database))
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={
                "title": "Two public turns",
                "prompt": "PRIVATE initial prompt",
                "public_content": "first user",
                "workspace": str(tmp_path),
            },
        )
    )
    task_id = str(created.body["task_id"])
    root_id = SessionId(UUID(task_id))
    root = SQLiteProjectionStore(database).get_session(root_id)
    assert root is not None
    root_events = (
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 2,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "first final", "tool_call_count": 0},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=root_id,
            sequence=root.current_sequence + 3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    )
    event_store = SQLiteEventStore(database)
    for event in root_events:
        event_store.append(event)
        root = apply_event(root, event)
    SQLiteProjectionStore(database).save_session(root)

    appended = adapter.handle(
        RouteRequest(
            "POST",
            f"/tasks/{task_id}/messages",
            body={
                "content": "PRIVATE follow-up harness input",
                "public_content": "follow-up user",
            },
        )
    )
    segments = adapter.handle(RouteRequest("GET", f"/internal/tasks/{task_id}/segments"))
    child_id = SessionId(UUID(segments.body["segments"][-1]["session_id"]))
    child = SQLiteProjectionStore(database).get_session(child_id)
    assert child is not None
    event_store.append(
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 1,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "follow-up final", "tool_call_count": 0},
            created_at=NOW,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=child_id,
            sequence=child.current_sequence + 2,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        )
    )

    conversation = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}/conversation"))
    first_final_cursor = next(
        item["cursor"]
        for item in conversation.body["items"]
        if item["role"] == "final_response" and item["content"] == "first final"
    )
    tail = adapter.handle(
        RouteRequest(
            "GET",
            f"/tasks/{task_id}/conversation",
            query={"after_sequence": str(first_final_cursor)},
        )
    )

    assert created.status_code == 201
    assert appended.status_code == 201
    assert appended.body["task_id"] == task_id
    assert appended.body["rolled_over"] is True
    assert [
        (item["role"], item["content"])
        for item in conversation.body["items"]
        if item["role"] in {"user_message", "final_response"}
    ] == [
        ("user_message", "first user"),
        ("final_response", "first final"),
        ("user_message", "follow-up user"),
        ("final_response", "follow-up final"),
    ]
    assert "PRIVATE initial prompt" not in str(conversation.body)
    assert "PRIVATE follow-up harness input" not in str(conversation.body)
    assert [
        (item["role"], item["content"])
        for item in tail.body["items"]
        if item["role"] in {"user_message", "final_response"}
    ] == [
        ("user_message", "follow-up user"),
        ("final_response", "follow-up final"),
    ]
