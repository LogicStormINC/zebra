from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent_core.application.public_conversation import project_public_conversation
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.agent_tasks import TaskEvent

NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _task_event(
    task_id: TaskId,
    segment_id: SessionId,
    task_sequence: int,
    event_type: EventType,
    payload: dict[str, object],
) -> TaskEvent:
    return TaskEvent(
        task_id=task_id,
        task_sequence=task_sequence,
        segment_id=segment_id,
        segment_sequence=task_sequence,
        event=SessionEvent(
            event_id=EventId(uuid4()),
            session_id=segment_id,
            sequence=task_sequence,
            event_type=event_type,
            payload=payload,
            actor=EventActor.HARNESS,
            created_at=NOW + timedelta(seconds=task_sequence),
        ),
    )


def test_stable_task_keeps_each_public_user_and_final_turn_in_cursor_order() -> None:
    task_id = TaskId(uuid4())
    segment_id = SessionId(uuid4())
    projection = project_public_conversation(
        task_id,
        (
            _task_event(
                task_id,
                segment_id,
                1,
                EventType.USER_MESSAGE_RECEIVED,
                {
                    "content": "PRIVATE system prompt and grant",
                    "public_content": "first user",
                },
            ),
            _task_event(
                task_id,
                segment_id,
                10,
                EventType.TOOL_EXECUTION_COMPLETED,
                {
                    "tool_name": "finos.journals.get",
                    "tool_call_id": "tool-1",
                    "status": "executed",
                    "arguments": {"grant": "PRIVATE grant"},
                    "output": "PRIVATE raw tool output",
                },
            ),
            _task_event(
                task_id,
                segment_id,
                47,
                EventType.MODEL_RESPONSE_RECEIVED,
                {
                    "assistant_message": "first final",
                    "response_stage": "final",
                    "reasoning_content": "PRIVATE first reasoning",
                },
            ),
            _task_event(
                task_id,
                segment_id,
                55,
                EventType.USER_MESSAGE_RECEIVED,
                {
                    "content": "PRIVATE follow-up prompt",
                    "public_content": "follow-up user",
                },
            ),
            _task_event(
                task_id,
                segment_id,
                156,
                EventType.MODEL_RESPONSE_RECEIVED,
                {
                    "assistant_message": "follow-up final",
                    "response_stage": "final",
                },
            ),
        ),
    )

    visible_turns = [
        (item.cursor, item.role, item.content)
        for item in projection.items
        if item.role in {"user_message", "final_response"}
    ]
    assert visible_turns == [
        (1, "user_message", "first user"),
        (47, "final_response", "first final"),
        (55, "user_message", "follow-up user"),
        (156, "final_response", "follow-up final"),
    ]
    assert projection.next_cursor == 156
    assert "PRIVATE system prompt and grant" not in str(projection)
    assert "PRIVATE follow-up prompt" not in str(projection)
    assert "PRIVATE first reasoning" not in str(projection)
    assert "PRIVATE grant" not in str(projection)
    assert "PRIVATE raw tool output" not in str(projection)
