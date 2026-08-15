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


def test_stable_task_keeps_public_history_across_completed_segments() -> None:
    task_id = TaskId(uuid4())
    first_segment_id = SessionId(uuid4())
    second_segment_id = SessionId(uuid4())
    projection = project_public_conversation(
        task_id,
        (
            _task_event(
                task_id,
                first_segment_id,
                1,
                EventType.USER_MESSAGE_RECEIVED,
                {
                    "content": "PRIVATE system prompt and grant",
                    "public_content": "first user",
                },
            ),
            _task_event(
                task_id,
                first_segment_id,
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
                first_segment_id,
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
                first_segment_id,
                48,
                EventType.SESSION_COMPLETED,
                {"summary": "first done"},
            ),
            _task_event(
                task_id,
                second_segment_id,
                55,
                EventType.USER_MESSAGE_RECEIVED,
                {
                    "content": "PRIVATE follow-up prompt",
                    "public_content": "follow-up user",
                },
            ),
            _task_event(
                task_id,
                second_segment_id,
                156,
                EventType.MODEL_RESPONSE_RECEIVED,
                {
                    "assistant_message": "follow-up final",
                    "response_stage": "final",
                },
            ),
            _task_event(
                task_id,
                second_segment_id,
                157,
                EventType.SESSION_COMPLETED,
                {"summary": "follow-up done"},
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
    assert projection.next_cursor == 157
    assert "PRIVATE system prompt and grant" not in str(projection)
    assert "PRIVATE follow-up prompt" not in str(projection)
    assert "PRIVATE first reasoning" not in str(projection)
    assert "PRIVATE grant" not in str(projection)
    assert "PRIVATE raw tool output" not in str(projection)


def test_public_projection_excludes_provisional_tool_loop_response() -> None:
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
                {"public_content": "submit the candidate"},
            ),
            _task_event(
                task_id,
                segment_id,
                10,
                EventType.MODEL_RESPONSE_RECEIVED,
                {
                    "assistant_message": "The candidate was submitted successfully.",
                    "response_stage": "tool_loop",
                },
            ),
            _task_event(
                task_id,
                segment_id,
                11,
                EventType.MODEL_RESPONSE_RECEIVED,
                {
                    "assistant_message": "The tool failed; no candidate was submitted.",
                    "response_stage": "final",
                },
            ),
        ),
    )

    final_items = [item for item in projection.items if item.role == "final_response"]

    assert [(item.cursor, item.content) for item in final_items] == [
        (11, "The tool failed; no candidate was submitted.")
    ]


def test_public_projection_keeps_only_terminal_explicit_final_per_segment() -> None:
    task_id = TaskId(uuid4())
    segment_id = SessionId(uuid4())
    events = (
        _task_event(
            task_id,
            segment_id,
            182,
            EventType.MODEL_RESPONSE_RECEIVED,
            {
                "assistant_message": "superseded final",
                "response_stage": "final",
                "tool_call_count": 0,
            },
        ),
        _task_event(
            task_id,
            segment_id,
            190,
            EventType.TOOL_EXECUTION_COMPLETED,
            {
                "tool_name": "files.read",
                "tool_call_id": "continued-work",
                "status": "executed",
            },
        ),
        _task_event(
            task_id,
            segment_id,
            250,
            EventType.MODEL_RESPONSE_RECEIVED,
            {
                "assistant_message": "terminal final",
                "response_stage": "final",
                "tool_call_count": 0,
            },
        ),
        _task_event(
            task_id,
            segment_id,
            252,
            EventType.SESSION_COMPLETED,
            {"summary": "done"},
        ),
    )

    projection = project_public_conversation(task_id, events)
    tail = project_public_conversation(task_id, events, after_sequence=182)

    assert [
        (item.cursor, item.content)
        for item in projection.items
        if item.role == "final_response"
    ] == [(250, "terminal final")]
    assert [
        (item.cursor, item.content)
        for item in tail.items
        if item.role == "final_response"
    ] == [(250, "terminal final")]
    assert projection.next_cursor == tail.next_cursor == 252


def test_public_projection_keeps_one_explicit_final_for_each_completed_segment() -> None:
    task_id = TaskId(uuid4())
    first_segment = SessionId(uuid4())
    second_segment = SessionId(uuid4())

    projection = project_public_conversation(
        task_id,
        (
            _task_event(
                task_id,
                first_segment,
                10,
                EventType.MODEL_RESPONSE_RECEIVED,
                {"assistant_message": "first final", "response_stage": "final"},
            ),
            _task_event(
                task_id,
                first_segment,
                11,
                EventType.SESSION_COMPLETED,
                {"summary": "first done"},
            ),
            _task_event(
                task_id,
                second_segment,
                20,
                EventType.MODEL_RESPONSE_RECEIVED,
                {"assistant_message": "second final", "response_stage": "final"},
            ),
            _task_event(
                task_id,
                second_segment,
                21,
                EventType.SESSION_COMPLETED,
                {"summary": "second done"},
            ),
        ),
    )

    assert [
        (item.cursor, item.content)
        for item in projection.items
        if item.role == "final_response"
    ] == [(10, "first final"), (20, "second final")]


def test_public_projection_keeps_single_explicit_final_across_suspend_resume() -> None:
    task_id = TaskId(uuid4())
    segment_id = SessionId(uuid4())

    projection = project_public_conversation(
        task_id,
        (
            _task_event(
                task_id,
                segment_id,
                10,
                EventType.MODEL_RESPONSE_RECEIVED,
                {"assistant_message": "single final", "response_stage": "final"},
            ),
            _task_event(
                task_id,
                segment_id,
                11,
                EventType.SESSION_SUSPENDED,
                {"reason": "provider retry"},
            ),
            _task_event(
                task_id,
                segment_id,
                12,
                EventType.SESSION_RESUMED,
                {"reason": "provider recovered"},
            ),
        ),
    )

    assert [
        (item.cursor, item.content)
        for item in projection.items
        if item.role == "final_response"
    ] == [(10, "single final")]


def test_public_projection_keeps_legacy_completed_final() -> None:
    task_id = TaskId(uuid4())
    segment_id = SessionId(uuid4())

    projection = project_public_conversation(
        task_id,
        (
            _task_event(
                task_id,
                segment_id,
                10,
                EventType.MODEL_RESPONSE_RECEIVED,
                {"assistant_message": "legacy final", "tool_call_count": 0},
            ),
            _task_event(
                task_id,
                segment_id,
                11,
                EventType.SESSION_COMPLETED,
                {"summary": "done"},
            ),
        ),
    )

    assert [
        (item.cursor, item.content)
        for item in projection.items
        if item.role == "final_response"
    ] == [(10, "legacy final")]
