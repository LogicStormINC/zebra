"""Reference-equivalent frames with bounded private-prefix projection work."""

from dataclasses import replace

import pytest
from ag_ui.encoder import EventEncoder
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId, new_session_id
from agent_core.ports.agent_tasks import TaskEvent
from agent_integrations.ag_ui import AgUiCursor, AgUiProjectionError
from agent_integrations.ag_ui.task_run_binding import bind_task_run
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_integrations.coverage_public_events import strict_coverage_events
from zebra_agent_api.ag_ui_task_frames import project_new_task_events

from tests.agent_integrations.test_ag_ui_coverage_projection import stream
from tests.agent_integrations.test_coverage_public_events import event


def reference(events, identity, after):
    """The reviewed Public20 per-prefix implementation, unchanged algorithm."""
    result, previous = [], after
    binding = bind_task_run(events, identity.run_id)
    strict = strict_coverage_events(entry.event for entry in events)
    projector, encoder = AgUiTaskProjector(), EventEncoder()
    for index, entry in enumerate(events):
        if (
            (after is not None and entry.task_sequence <= after.sequence)
            or not binding.includes(entry)
        ):
            continue
        projection = projector.project_task(
            events[:index + 1], identity, after=previous, strict_coverage=strict,
        )
        cursor = projection.next_cursor
        if cursor is not None:
            result.extend((cursor, f"id: {cursor.encode()}\n{encoder.encode(item)}")
                          for item in projection.events)
            previous = cursor
    return result


def private_stream(count=100, *, strict=True, identity=None):
    if identity is None:
        _, identity = stream()
    task = TaskId(identity.session_id)
    identity = identity.model_copy(update={"thread_id": str(task)})
    raw = [event(EventType.MODEL_RESPONSE_RECEIVED, i,
                 {"assistant_message": "PRIVATE"}, identity.session_id) for i in range(count)]
    raw.append(event(EventType.TASK_PREPARED, count,
                     {"title": "strict", "coverage_admission": None} if strict else
                     {"title": "ordinary"}, identity.session_id))
    return identity, tuple(TaskEvent(task, i, row.session_id, row.sequence, row)
                           for i, row in enumerate(raw))


def test_private_tail_projection_count_drops_without_changing_frames(monkeypatch):
    identity, rows = private_stream(500)
    expected = reference(rows, identity, None)
    original = AgUiTaskProjector.project_task
    calls = []

    def counted(self, events, *args, **kwargs):
        calls.append(len(events))
        return original(self, events, *args, **kwargs)

    monkeypatch.setattr(AgUiTaskProjector, "project_task", counted)
    assert project_new_task_events(rows, identity, None) == expected
    assert calls == [501, 1]  # full validation plus first Segment's RUN_STARTED
    assert sum(calls) < len(rows) * (len(rows) + 1) // 2


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("reconnect", [True, False])
def test_ordinary_and_strict_reconnect_frames_match_reference(strict, reconnect):
    identity, rows = private_stream(20, strict=strict)
    after = None if not reconnect else AgUiCursor(
        thread_id=identity.thread_id, run_id=identity.run_id, sequence=7,
        event_id=str(rows[7].event.event_id),
    )
    assert project_new_task_events(rows, identity, after) == reference(rows, identity, after)


def test_hidden_segment_transition_still_emits_its_start():
    identity, rows = private_stream(3)
    segment = new_session_id()
    tail = tuple(TaskEvent(rows[0].task_id, len(rows) + i, segment, i,
                          event(EventType.MODEL_RESPONSE_RECEIVED, i,
                                {"assistant_message": "PRIVATE"}, segment)) for i in range(3))
    rows += tail
    actual = project_new_task_events(rows, identity, None)
    assert actual == reference(rows, identity, None)
    assert len(actual) == 2


@pytest.mark.parametrize("reconnect", [False, True])
def test_returning_segment_after_excluded_slice_keeps_start_cursor(reconnect):
    identity, base = private_stream(1)
    segment, excluded = identity.session_id, new_session_id()
    raw = (
        (segment, 0, EventType.SESSION_COMMAND_ACCEPTED,
         {"kind": "run", "payload": {"run_id": identity.run_id}}),
        (segment, 1, EventType.TASK_PREPARED, {"coverage_admission": None}),
        (excluded, 0, EventType.MODEL_RESPONSE_RECEIVED,
         {"assistant_message": "EXCLUDED_PRIVATE"}),
        (segment, 2, EventType.MODEL_RESPONSE_RECEIVED,
         {"assistant_message": "RETURN_PRIVATE"}),
    )
    rows = tuple(TaskEvent(base[0].task_id, i, sid, sequence,
                           event(kind, sequence, payload, sid))
                 for i, (sid, sequence, kind, payload) in enumerate(raw))
    after = AgUiCursor(thread_id=identity.thread_id, run_id=identity.run_id,
                       sequence=1, event_id=str(rows[1].event.event_id)) if reconnect else None
    actual = project_new_task_events(rows, identity, after)
    assert actual == reference(rows, identity, after)
    assert [cursor.sequence for cursor, _ in actual] == ([3] if reconnect else [0, 3])
    assert "PRIVATE" not in "".join(frame for _, frame in actual)


def test_progress_after_private_events_keeps_exact_frames_and_source_cursors():
    raw, identity = stream()
    identity, rows = private_stream(30, identity=identity)
    rows += tuple(TaskEvent(rows[0].task_id, len(rows) + i, identity.session_id,
                            len(rows) + i, entry.model_copy(update={"sequence": len(rows) + i}))
                  for i, entry in enumerate(raw))
    actual = project_new_task_events(rows, identity, None)
    assert actual == reference(rows, identity, None)
    assert len(actual) == 5


def test_invalid_private_tail_is_not_skipped():
    identity, rows = private_stream(20)
    rows = (*rows[:-1], replace(rows[-1], task_sequence=1000))
    with pytest.raises(AgUiProjectionError, match="contiguous"):
        project_new_task_events(rows, identity, None)


def test_invalid_reconnect_anchor_is_not_skipped():
    identity, rows = private_stream(20)
    after = AgUiCursor(thread_id=identity.thread_id, run_id=identity.run_id,
                       sequence=7, event_id="not-original")
    with pytest.raises(AgUiProjectionError, match="canonical"):
        project_new_task_events(rows, identity, after)
