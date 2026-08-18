"""Task-level AG-UI stream tests: rollover continuity and task cursors."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui import (
    AgUiCursor,
    AgUiProjectionError,
    AgUiRunIdentity,
)
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector

TASK_ID = TaskId(uuid4())
SEGMENT_A = SessionId(uuid4())
SEGMENT_B = SessionId(uuid4())
IDENTITY = AgUiRunIdentity(
    session_id=SEGMENT_A,
    thread_id=str(TASK_ID),
    run_id="run-1",
)


def _event(session: SessionId, sequence: int, text: str) -> SessionEvent:
    return SessionEvent.create(
        session_id=session,
        sequence=sequence,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload={"model_call_id": f"call-{sequence}", "assistant_message": text},
        created_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )


def _task_event(task_sequence: int, segment: SessionId, sequence: int, text: str) -> TaskEvent:
    return TaskEvent(
        task_id=TASK_ID,
        task_sequence=task_sequence,
        segment_id=segment,
        segment_sequence=sequence,
        event=_event(segment, sequence, text),
    )


def _two_segment_stream() -> list[TaskEvent]:
    return [
        _task_event(0, SEGMENT_A, 0, "hello"),
        _task_event(1, SEGMENT_A, 1, "from segment a"),
        _task_event(2, SEGMENT_B, 0, "continuing after rollover"),
        _task_event(3, SEGMENT_B, 1, "still continuous"),
    ]


class TestTaskProjector:
    def test_full_stream_projects_across_rollover(self) -> None:
        projection = AgUiTaskProjector().project_task(_two_segment_stream(), IDENTITY)
        assert projection.next_cursor is not None
        assert projection.next_cursor.sequence == 3
        assert len(projection.events) > 0

    def test_resume_from_task_cursor_crosses_segments(self) -> None:
        full = _two_segment_stream()
        first = AgUiTaskProjector().project_task(full[:2], IDENTITY)
        assert first.next_cursor is not None
        resumed = AgUiTaskProjector().project_task(full, IDENTITY, after=first.next_cursor)
        assert resumed.next_cursor is not None
        assert resumed.next_cursor.sequence == 3
        assert all(
            event.sequence > first.next_cursor.sequence
            for event in [resumed.next_cursor]
        )
        assert len(resumed.events) > 0

    def test_cursor_from_foreign_run_is_rejected(self) -> None:
        foreign = AgUiCursor(
            thread_id=str(TASK_ID),
            run_id="other-run",
            sequence=1,
            event_id=str(uuid4()),
        )
        try:
            AgUiTaskProjector().project_task(_two_segment_stream(), IDENTITY, after=foreign)
        except AgUiProjectionError:
            pass
        else:
            raise AssertionError("foreign run cursor must be rejected")

    def test_out_of_order_task_events_are_rejected(self) -> None:
        stream = _two_segment_stream()
        broken = [stream[1], stream[0]]
        try:
            AgUiTaskProjector().project_task(broken, IDENTITY)
        except AgUiProjectionError:
            pass
        else:
            raise AssertionError("task events must be ordered")

    def test_empty_stream_has_no_cursor(self) -> None:
        projection = AgUiTaskProjector().project_task([], IDENTITY)
        assert projection.next_cursor is None
        assert projection.events == ()


class TestSegmentContinuation:
    def test_segment_boundary_emits_continuation_events(self) -> None:
        full = _two_segment_stream()
        prefix_a = AgUiTaskProjector().project_task(full[:2], IDENTITY)
        assert prefix_a.next_cursor is not None
        continuation = AgUiTaskProjector().project_task(full, IDENTITY, after=prefix_a.next_cursor)
        rendered = [type(event).__name__ for event in continuation.events]
        assert "RunStartedEvent" in rendered, "a new Segment continues as a new run"
        assert any(name.startswith("TextMessage") for name in rendered)

    def test_event_ids_are_unique_across_segments(self) -> None:
        full = _two_segment_stream()
        ids = {str(entry.event.event_id) for entry in full}
        assert len(ids) == 4
        # sanity: segment sequences restart but task sequences do not
        assert [entry.task_sequence for entry in full] == [0, 1, 2, 3]
        assert [entry.segment_sequence for entry in full] == [0, 1, 0, 1]


def test_task_id_roundtrip() -> None:
    # thread identity stays the Task UUID across both segments
    assert UUID(IDENTITY.thread_id) == TASK_ID
