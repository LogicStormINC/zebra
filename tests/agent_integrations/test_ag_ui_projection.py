from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ag_ui.core import Event as AgUiEvent
from ag_ui.core import EventType as AgUiEventType
from ag_ui.core import RunErrorEvent, RunFinishedEvent, RunFinishedInterruptOutcome
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_event_id, new_session_id
from agent_integrations.ag_ui import (
    AgUiCursor,
    AgUiProjectionError,
    AgUiProjector,
    AgUiResumeEntry,
    AgUiResumeRequest,
    AgUiRunIdentity,
    resume_run_id,
)
from pydantic import TypeAdapter

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)


def _event(
    session_id: SessionId,
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
) -> SessionEvent:
    return SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        actor=EventActor.HARNESS,
        created_at=NOW,
    )


def _identity(session_id: SessionId) -> AgUiRunIdentity:
    return AgUiRunIdentity(session_id=session_id, thread_id="task-1", run_id="segment-1")


def _golden_events(session_id: SessionId) -> tuple[SessionEvent, ...]:
    return (
        _event(
            session_id,
            0,
            EventType.TASK_PREPARED,
            {"title": "Inspect repository", "user_input": "Inspect"},
        ),
        _event(
            session_id,
            1,
            EventType.MODEL_RESPONSE_DELTA,
            {
                "attempt_number": 1,
                "model_call_id": "model-1",
                "delta_index": 0,
                "content_delta": "Found ",
            },
        ),
        _event(
            session_id,
            2,
            EventType.MODEL_RESPONSE_DELTA,
            {
                "attempt_number": 1,
                "model_call_id": "model-1",
                "delta_index": 1,
                "content_delta": "evidence.",
            },
        ),
        _event(
            session_id,
            3,
            EventType.MODEL_RESPONSE_RECEIVED,
            {
                "attempt_number": 1,
                "model_call_id": "model-1",
                "assistant_message": "Found evidence.",
            },
        ),
        _event(
            session_id,
            4,
            EventType.TOOL_CALL_PROPOSED,
            {
                "attempt_number": 1,
                "tool_name": "repo.read",
                "tool_call_id": "tool-1",
                "arguments": {"path": "README.md"},
            },
        ),
        _event(
            session_id,
            5,
            EventType.TOOL_EXECUTION_COMPLETED,
            {
                "attempt_number": 1,
                "tool_name": "repo.read",
                "tool_call_id": "tool-1",
                "status": "executed",
                "output": "README",
                "metadata": {},
            },
        ),
        _event(session_id, 6, EventType.SESSION_COMPLETED, {"summary": "done"}),
    )


def test_golden_text_tool_state_and_terminal_events_are_officially_valid() -> None:
    session_id = new_session_id()
    projection = AgUiProjector().project(_golden_events(session_id), _identity(session_id))

    assert [event.type for event in projection.events] == [
        AgUiEventType.RUN_STARTED,
        AgUiEventType.STATE_SNAPSHOT,
        AgUiEventType.TEXT_MESSAGE_START,
        AgUiEventType.TEXT_MESSAGE_CONTENT,
        AgUiEventType.TEXT_MESSAGE_CONTENT,
        AgUiEventType.TEXT_MESSAGE_END,
        AgUiEventType.TOOL_CALL_START,
        AgUiEventType.TOOL_CALL_ARGS,
        AgUiEventType.TOOL_CALL_END,
        AgUiEventType.TOOL_CALL_RESULT,
        AgUiEventType.RUN_FINISHED,
    ]
    for event in projection.events:
        TypeAdapter(AgUiEvent).validate_python(event.model_dump(mode="json", by_alias=True))
    assert projection.next_cursor is not None
    assert projection.next_cursor.sequence == 6


def test_reconnect_tail_requires_exact_cursor_and_replays_only_new_durable_events() -> None:
    session_id = new_session_id()
    events = _golden_events(session_id)
    identity = _identity(session_id)
    cursor = AgUiCursor(
        thread_id=identity.thread_id,
        run_id=identity.run_id,
        sequence=3,
        event_id=str(events[3].event_id),
    )

    tail = AgUiProjector().project(events, identity, after=cursor.encode())

    assert tail.replayed_from == cursor
    assert AgUiEventType.RUN_STARTED not in [event.type for event in tail.events]
    assert [event.type for event in tail.events] == [
        AgUiEventType.TOOL_CALL_START,
        AgUiEventType.TOOL_CALL_ARGS,
        AgUiEventType.TOOL_CALL_END,
        AgUiEventType.TOOL_CALL_RESULT,
        AgUiEventType.RUN_FINISHED,
    ]

    with pytest.raises(AgUiProjectionError, match="exact durable Event"):
        AgUiProjector().project(
            events,
            identity,
            after=cursor.model_copy(update={"event_id": "wrong-event"}),
        )


def test_projection_rejects_mixed_sessions_and_non_monotonic_sequences() -> None:
    session_id = new_session_id()
    events = _golden_events(session_id)
    other_session_event = _event(new_session_id(), 7, EventType.SESSION_COMPLETED, {})
    with pytest.raises(AgUiProjectionError, match="different durable session"):
        AgUiProjector().project((*events, other_session_event), _identity(session_id))

    with pytest.raises(AgUiProjectionError, match="unique increasing sequences"):
        AgUiProjector().project((events[1], events[0]), _identity(session_id))


def test_interrupt_projection_orders_snapshots_before_finish_and_resume_is_deterministic() -> None:
    session_id = new_session_id()
    event = _event(
        session_id,
        0,
        EventType.CLARIFICATION_REQUESTED,
        {
            "attempt_number": 1,
            "clarification_id": "clarify-1",
            "tool_call_id": "clarify-1",
            "question": "Which scope?",
            "choices": ["event", "topic"],
            "assistant_message": "Choose a scope.",
            "conversation": [],
            "model_calls_used": 1,
            "tool_calls_executed": 0,
            "response_schema": {"type": "string"},
        },
    )
    projection = AgUiProjector().project((event,), _identity(session_id))

    assert [item.type for item in projection.events] == [
        AgUiEventType.RUN_STARTED,
        AgUiEventType.STATE_SNAPSHOT,
        AgUiEventType.MESSAGES_SNAPSHOT,
        AgUiEventType.RUN_FINISHED,
    ]
    finished = projection.events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert isinstance(finished.outcome, RunFinishedInterruptOutcome)
    interrupt_id = finished.outcome.interrupts[0].id
    entries = [
        AgUiResumeEntry(
            interrupt_id=interrupt_id,
            status="resolved",
            payload={"scope": "event"},
        )
    ]
    request = AgUiResumeRequest(thread_id="task-1", run_id="segment-1", entries=tuple(entries))
    reversed_request = AgUiResumeRequest(
        thread_id="task-1", run_id="segment-1", entries=tuple(reversed(entries))
    )
    assert request.idempotency_key == reversed_request.idempotency_key
    assert resume_run_id("segment-1", entries) == resume_run_id("segment-1", reversed(entries))


def test_failure_projects_to_bounded_ag_ui_error() -> None:
    session_id = new_session_id()
    event = _event(session_id, 0, EventType.SESSION_FAILED, {"summary": "policy blocked"})

    projection = AgUiProjector().project((event,), _identity(session_id))

    assert [item.type for item in projection.events] == [
        AgUiEventType.RUN_STARTED,
        AgUiEventType.RUN_ERROR,
    ]
    error = projection.events[-1]
    assert isinstance(error, RunErrorEvent)
    assert error.message == "policy blocked"
