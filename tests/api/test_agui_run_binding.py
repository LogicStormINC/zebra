"""Exact run windows, canonical cursor anchors, and read-only error frames."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_integrations.ag_ui import AgUiCursor, AgUiProjectionError
from agent_integrations.ag_ui.task_run_binding import bind_task_run
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from zebra_agent_api.ag_ui_stream import _has_run_terminal_event, _project_new_task_events

from tests.api.test_ag_ui_task_stream import IDENTITY, SEGMENT_A, SEGMENT_B, _task_event


def _entry(index, kind=None, run="run-1", *, event_type=None, segment=SEGMENT_A, payload=None):
    entry = _task_event(index, segment, index, f"text-{index}")
    if kind is not None:
        event_type = EventType.SESSION_COMMAND_ACCEPTED
        payload = {"kind": kind, "payload": {"run_id": run}}
    return replace(
        entry,
        event=entry.event.model_copy(
            update={
                "event_type": event_type or entry.event.event_type,
                "payload": payload if payload is not None else entry.event.payload,
            }
        ),
    )


@pytest.mark.parametrize("sequence,event_id", [(1, str(uuid4())), (100, str(uuid4()))])
def test_cursor_requires_exact_event_and_existing_task_sequence(sequence, event_id):
    events = [_entry(0, "run"), _entry(1)]
    cursor = AgUiCursor(
        thread_id=IDENTITY.thread_id, run_id=IDENTITY.run_id, sequence=sequence, event_id=event_id
    )
    with pytest.raises(AgUiProjectionError):
        AgUiTaskProjector().project_task(events, IDENTITY, after=cursor)


def test_later_run_terminal_never_closes_or_leaks_into_first_run():
    events = [
        _entry(0, "run"),
        _entry(1),
        _entry(2, "run", "run-two"),
        _entry(3, event_type=EventType.SESSION_COMPLETED, payload={}),
    ]
    assert not _has_run_terminal_event(events, "run-1")
    output = "".join(frame for _, frame in _project_new_task_events(events, IDENTITY, None))
    assert "text-1" in output and "RUN_FINISHED" not in output
    cursor = AgUiCursor(
        thread_id=IDENTITY.thread_id,
        run_id=IDENTITY.run_id,
        sequence=3,
        event_id=str(events[-1].event.event_id),
    )
    with pytest.raises(AgUiProjectionError, match="outside"):
        AgUiTaskProjector().project_task(events, IDENTITY, after=cursor)


def test_unique_execution_wins_over_controls_but_duplicate_execution_is_ambiguous():
    events = [_entry(0, "run"), _entry(1, "suspend")]
    assert bind_task_run(events, "run-1").anchor == events[0]
    with pytest.raises(AgUiProjectionError, match="ambiguous"):
        bind_task_run([*events, _entry(2, "resume")], "run-1")
    controls = [_entry(0, "suspend")]
    assert AgUiTaskProjector().project_task(controls, IDENTITY).events == ()
    with pytest.raises(AgUiProjectionError, match="ambiguous"):
        bind_task_run([*controls, _entry(1, "stop")], "run-1")


def test_internal_child_wakeup_continues_original_run_through_terminal() -> None:
    wakeup = _entry(
        2,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        payload={
            "kind": "resume",
            "idempotency_key": "child-wakeup:parent",
            "payload": {"child_results": []},
        },
    )
    wakeup = replace(wakeup, event=wakeup.event.model_copy(update={"actor": EventActor.HARNESS}))
    terminal = _entry(3, event_type=EventType.SESSION_FAILED, payload={"summary": "failed"})
    events = [_entry(0, "run"), _entry(1), wakeup, terminal]

    binding = bind_task_run(events, "run-1")

    assert binding.stop is None
    assert binding.includes(terminal)
    assert _has_run_terminal_event(events, "run-1")
    projection = AgUiTaskProjector().project_task(events, IDENTITY)
    assert projection.next_cursor is not None
    assert projection.next_cursor.sequence == 3
    assert any(event.type == "RUN_ERROR" for event in projection.events)


def test_unrelated_segment_terminal_cannot_end_run_but_paired_handoff_can():
    committed = _entry(
        1,
        event_type=EventType.SESSION_HANDOFF_COMMITTED,
        payload={"handoff_id": "h", "target_session_id": str(SEGMENT_B)},
    )
    received = _entry(
        2,
        segment=SEGMENT_B,
        event_type=EventType.SESSION_HANDOFF_RECEIVED,
        payload={"handoff_id": "h", "parent_session_id": str(SEGMENT_A)},
    )
    terminal = _entry(3, segment=SEGMENT_B, event_type=EventType.SESSION_COMPLETED, payload={})
    assert not _has_run_terminal_event([_entry(0, "run"), terminal], "run-1")
    assert _has_run_terminal_event([_entry(0, "run"), committed, received, terminal], "run-1")


def test_subscribe_before_admit_does_not_replay_other_run():
    events = [_entry(0, "run", "older")]
    assert AgUiTaskProjector().project_task(events, IDENTITY).events == ()


def test_task_and_segment_index_identity_must_match_canonical():
    events = [_entry(0, "run")]
    with pytest.raises(AgUiProjectionError):
        AgUiTaskProjector().project_task([replace(events[0], segment_id=SEGMENT_B)], IDENTITY)


@pytest.mark.parametrize("reconnect", [False, True])
def test_durable_failure_has_no_sse_id_and_does_not_write_events(tmp_path, reconnect):
    from agent_storage import SQLiteEventStore, sqlite_control_plane_stores
    from zebra_agent_api.ag_ui_stream import (
        AgUiStreamContext,
        prepare_agui_stream,
        tail_agui_events,
    )

    from tests.agent_storage.test_command_wakeup import _binding
    from tests.api.test_agui_stream_routes import (
        _append,
        _FakeRequest,
        _seed_ready_session,
        _stream_path,
    )

    path, session, sequence = _seed_ready_session(tmp_path)
    store = SQLiteEventStore(path)
    accepted = _append(
        store,
        session,
        sequence,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"payload": {"run_id": "failing"}},
    )
    cursor = AgUiCursor(
        thread_id=str(session), run_id="failing", sequence=sequence, event_id=str(accepted.event_id)
    )
    calls = []

    def outcome(*args):
        calls.append(args)
        return "command_requires_reconciliation"

    context = prepare_agui_stream(
        sqlite_control_plane_stores(path),
        _stream_path(session, "failing"),
        {"cursor": cursor.encode()} if reconnect else {},
        command_outcome=outcome,
        host_context=_binding(str(session)).host_capability.host_context,
    )
    assert isinstance(context, AgUiStreamContext)
    before = store.list_for_session(session)

    async def consume():
        return [frame async for frame in tail_agui_events(context, _FakeRequest())]

    frames = asyncio.run(consume())
    errors = [frame for frame in frames if "RUN_ERROR" in frame]
    assert len(errors) == 1 and not errors[0].startswith("id:")
    assert "command_requires_reconciliation" in errors[0]
    assert calls[0][2] == accepted.event_id
    assert store.list_for_session(session) == before
    assert context.cursor == (cursor if reconnect else None)


def test_reconnect_accepts_exact_unindexed_tail_cursor(tmp_path):
    from dataclasses import replace

    from agent_core.domain.identifiers import TaskId
    from agent_storage import SQLiteEventStore, sqlite_control_plane_stores
    from zebra_agent_api.ag_ui_stream import AgUiStreamContext, prepare_agui_stream

    from tests.api.test_agui_stream_routes import (
        _append,
        _FrozenTaskStore,
        _seed_ready_session,
        _stream_path,
    )

    path, session, sequence = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    frozen = _FrozenTaskStore(stores.tasks, TaskId(session))
    stores = replace(stores, tasks=frozen)
    event = _append(
        SQLiteEventStore(path),
        session,
        sequence,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "tail", "assistant_message": "tail"},
    )
    cursor = AgUiCursor(
        thread_id=str(session), run_id="legacy", sequence=sequence, event_id=str(event.event_id)
    )
    result = prepare_agui_stream(
        stores, _stream_path(session, "legacy"), {"cursor": cursor.encode()}
    )
    assert isinstance(result, AgUiStreamContext)


def test_steady_poll_does_not_reload_task_history_or_all_members(tmp_path, monkeypatch):
    from agent_core.domain.identifiers import TaskId
    from agent_storage import SQLiteEventStore, sqlite_control_plane_stores
    from zebra_agent_api import ag_ui_stream

    from tests.agent_storage.test_command_wakeup import _binding
    from tests.api.test_agui_stream_routes import (
        _append,
        _FakeRequest,
        _FrozenTaskStore,
        _seed_ready_session,
        _stream_path,
    )

    path, session, sequence = _seed_ready_session(tmp_path)
    _append(
        SQLiteEventStore(path),
        session,
        sequence,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"payload": {"run_id": "bounded"}},
    )
    stores = sqlite_control_plane_stores(path)

    class CountingTasks(_FrozenTaskStore):
        histories = 0
        memberships = 0

        def read_events(self, task_id, after_sequence):
            self.histories += 1
            return super().read_events(task_id, after_sequence)

        def segments(self, task_id):
            self.memberships += 1
            return super().segments(task_id)

    tasks = CountingTasks(stores.tasks, TaskId(session))
    stores = replace(stores, tasks=tasks)
    calls = []

    def outcome(*args):
        calls.append(args)
        return "command_delivery_failed" if len(calls) == 3 else None

    monkeypatch.setattr(ag_ui_stream, "_POLL_SECONDS", 0)
    context = ag_ui_stream.prepare_agui_stream(
        stores,
        _stream_path(session, "bounded"),
        {},
        command_outcome=outcome,
        host_context=_binding(str(session)).host_capability.host_context,
    )

    async def consume():
        return [frame async for frame in ag_ui_stream.tail_agui_events(context, _FakeRequest())]

    asyncio.run(consume())
    assert len(calls) == 3
    assert tasks.histories == tasks.memberships == 2  # prepare + first tail, not every tick


def test_slow_outcome_cannot_emit_after_authorization_expiry(tmp_path):
    from datetime import UTC, datetime, timedelta
    from time import sleep

    from agent_storage import SQLiteEventStore, sqlite_control_plane_stores
    from zebra_agent_api.ag_ui_stream import prepare_agui_stream, tail_agui_events

    from tests.agent_storage.test_command_wakeup import _binding
    from tests.api.test_agui_stream_routes import (
        _append,
        _FakeRequest,
        _seed_ready_session,
        _stream_path,
    )

    path, session, sequence = _seed_ready_session(tmp_path)
    _append(
        SQLiteEventStore(path),
        session,
        sequence,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"payload": {"run_id": "slow"}},
    )
    called = []

    def outcome(*args):
        called.append(True)
        sleep(0.15)
        return "command_delivery_failed"

    context = prepare_agui_stream(
        sqlite_control_plane_stores(path),
        _stream_path(session, "slow"),
        {},
        command_outcome=outcome,
        host_context=_binding(str(session)).host_capability.host_context,
    )

    async def consume():
        expiring = replace(
            context, authorization_expires_at=datetime.now(UTC) + timedelta(seconds=0.07)
        )
        return [frame async for frame in tail_agui_events(expiring, _FakeRequest())]

    frames = asyncio.run(consume())
    assert called == [True]
    assert not any("RUN_ERROR" in frame for frame in frames)


def test_consumer_pause_past_deadline_stops_before_resuming_projection(tmp_path):
    from datetime import UTC, datetime, timedelta

    from agent_storage import sqlite_control_plane_stores
    from zebra_agent_api.ag_ui_stream import prepare_agui_stream, tail_agui_events

    from tests.api.test_agui_stream_routes import _FakeRequest, _seed_ready_session, _stream_path

    path, session, _ = _seed_ready_session(tmp_path)
    context = prepare_agui_stream(
        sqlite_control_plane_stores(path), _stream_path(session, "local"), {}
    )

    async def consume():
        expiring = replace(
            context, authorization_expires_at=datetime.now(UTC) + timedelta(seconds=0.07)
        )
        stream = tail_agui_events(expiring, _FakeRequest())
        first = await anext(stream)
        assert "RUN_STARTED" in first  # another buffered projection frame would follow
        await asyncio.sleep(0.10)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(consume())


@pytest.mark.parametrize("frame", ["projection", "ambiguous-error", ": keepalive\n\n"])
def test_shared_frame_gate_checks_after_await_and_before_next_source_read(monkeypatch, frame):
    from zebra_agent_api import ag_ui_task_view

    clock = [0.0]
    reads = []
    monkeypatch.setattr(ag_ui_task_view, "monotonic", lambda: clock[0])

    async def source():
        reads.append(True)
        clock[0] = 2.0
        yield frame
        reads.append(True)

    async def consume():
        return [item async for item in ag_ui_task_view.deadline_frames(source(), 1.0)]

    assert asyncio.run(consume()) == []
    assert reads == [True]
