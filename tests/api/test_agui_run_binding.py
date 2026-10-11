"""Exact run windows, canonical cursor anchors, and read-only error frames."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_core.ports.task_projection_work import ProjectionWorkProblem
from agent_integrations.ag_ui import AgUiCursor, AgUiProjectionError
from agent_integrations.ag_ui.task_run_binding import bind_task_run
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from zebra_agent_api.ag_ui_stream import _has_run_terminal_event, _project_new_task_events

from tests.api.ag_ui_checkpoint_fixture import ObservationTasks, checkpoint_stores
from tests.api.ag_ui_checkpoint_fixture import checkpoint_backlog as _checkpoint_backlog
from tests.api.test_ag_ui_task_stream import IDENTITY, SEGMENT_A, SEGMENT_B, _task_event


@pytest.mark.parametrize(
    "code,attempts,scheduled,expected,retryable",
    [
        ("integrity", 1, False, "projection_conflict", False),
        ("budget", 1, False, "projection_budget_exceeded", False),
        ("projection_failed", 8, False, "observation_unavailable", False),
        ("projection_failed", 1, True, "projection_retry_scheduled", True),
        ("not_ready", 1, False, None, True),
        ("foreign-namespace", 1, False, "projection_conflict", False),
        ("foreign-anchor", 1, False, "projection_conflict", False),
        ("foreign-version", 1, False, "projection_conflict", False),
    ],
)
@pytest.mark.parametrize("prefix", [0, 260])
def test_exact_scope_persisted_problem_reaches_initial_head_tail_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    attempts: int,
    scheduled: bool,
    expected: str | None,
    retryable: bool,
    prefix: int,
) -> None:
    from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
    from zebra_agent_api.ag_ui_checkpoint_tail import tail_checkpoint_frames

    from tests.api.ag_ui_checkpoint_fixture import (
        SqlObservation,
        queue_problem_context,
        table_rows,
    )
    from tests.api.test_agui_stream_routes import _FakeRequest

    context = queue_problem_context(
        tmp_path,
        "budget" if code.startswith("foreign-") else code,
        attempts=attempts,
        retry_after=60 if scheduled else None,
        prefix=prefix,
    )
    snapshot = AgUiCheckpointObserver(context.stores.tasks, namespace="local").snapshot(
        context.task_id, context.identity
    )
    assert snapshot.run.anchor is not None
    assert snapshot.through >= 256 if prefix else snapshot.head.through_sequence == -1
    expected_frames = (
        [
            frame
            for _, frame in _project_new_task_events(
                tuple(
                    e
                    for e in context.stores.tasks.read_events(context.task_id, -1)
                    if e.task_sequence <= snapshot.through
                ),
                context.identity,
                None,
            )
        ]
        if prefix
        else []
    )
    work = context.stores.projection_work
    assert work is not None
    read, seen = work.read_projection_work_problem, []

    def scoped(scope: ProjectionScope) -> ProjectionWorkProblem | None:
        seen.append(scope)
        problem = read(scope)
        if code.startswith("foreign-") and problem is not None:
            changes = {
                "foreign-namespace": {"namespace": "foreign"},
                "foreign-anchor": {"anchor_event_id": uuid4()},
                "foreign-version": {"projector_version": "foreign-version"},
            }
            return replace(problem, scope=replace(scope, **changes[code]))
        return problem

    async def collect() -> list[str]:
        class Request(_FakeRequest):
            async def is_disconnected(self) -> bool:
                return bool(prefix and len(seen) >= 3)

        # Dense prefix replay and short-authorization expiry are separate contracts.
        # Stop scheduled/dependency waits after three actual scoped polling reads.
        async with asyncio.timeout(30 if prefix else 0.4):
            return [
                frame
                async for frame in tail_checkpoint_frames(
                    context,
                    Request(),
                    monotonic() + (30 if prefix else 0.08),
                    poll_seconds=0.005,
                    keepalive_seconds=0.005,
                )
            ]

    before = table_rows(tmp_path / "sessions.sqlite")
    with monkeypatch.context() as patch:
        patch.setattr(work, "read_projection_work_problem", scoped)
        sql = SqlObservation(patch, tmp_path / "sessions.sqlite", bodies=bool(prefix))
        frames = asyncio.run(collect())
        assert sql.writes == []
        if prefix:
            sql.assert_bounded_body_seeks(pages=2)
        else:
            assert sql.body_reads == []
    assert table_rows(tmp_path / "sessions.sqlite") == before
    assert seen and all(scope == snapshot.head.scope for scope in seen)
    notices = [
        json.loads(frame.removeprefix("data: ")) for frame in frames if frame.startswith("data: ")
    ]
    assert [frame for frame in frames if frame.startswith("id: ")] == expected_frames
    if expected is not None:
        assert frames[len(expected_frames)].startswith("data: ")
    assert not any("RUN_ERROR" in frame or "RUN_FINISHED" in frame for frame in frames)
    if expected is None:
        assert notices == []  # An open Run's dependency wait is not a Task failure.
    else:
        assert len(notices) == 1  # Scheduled retries must not flood each polling tick.
        assert notices[0]["type"] == "CUSTOM"
        assert notices[0]["name"] == "zebra.observation.problem"
        assert notices[0]["value"] == {"code": expected, "retryable": retryable}


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


def test_slow_replay_consumer_does_not_preencode_the_whole_event_backlog(monkeypatch):
    from zebra_agent_api import ag_ui_stream

    encoded = []
    monkeypatch.setattr(
        ag_ui_stream.EventEncoder, "encode", lambda self, event: encoded.append(event) or "frame"
    )
    events = [_entry(0, "run"), *(_entry(index) for index in range(1, 100))]
    slow = _project_new_task_events(events, IDENTITY, None)
    assert encoded == []
    next(slow)
    assert len(encoded) == 1
    fast = _project_new_task_events(events[:2], IDENTITY, None)
    assert len(list(fast)) > 1
    slow.close()
    assert len(encoded) < 10  # closing the blocked consumer never drains its backlog


def test_disconnect_after_each_frame_replays_the_rest_of_its_durable_event():
    events = [_entry(0, "run"), _entry(1)]
    expected = list(_project_new_task_events(events, IDENTITY, None))
    assert len(expected) >= 4
    assert len({cursor.encode() for cursor, _ in expected}) == len(expected)
    for index, (cursor, _) in enumerate(expected):
        interrupted = _project_new_task_events(events, IDENTITY, None)
        for _ in range(index + 1):
            next(interrupted)
        interrupted.close()
        resumed = list(_project_new_task_events(events, IDENTITY, cursor))
        assert expected[: index + 1] + resumed == expected


def test_frame_cursor_validates_position_but_legacy_event_cursor_still_skips_whole_event():
    events = [_entry(0, "run"), _entry(1)]
    legacy = AgUiCursor(
        thread_id=IDENTITY.thread_id,
        run_id=IDENTITY.run_id,
        sequence=1,
        event_id=str(events[-1].event.event_id),
    )
    assert list(_project_new_task_events(events, IDENTITY, legacy)) == []
    forged = legacy.model_copy(update={"frame_index": 99})
    with pytest.raises(AgUiProjectionError, match="frame"):
        AgUiTaskProjector().project_task(events, IDENTITY, after=forged)


def test_replay_projects_each_durable_event_once_not_each_repeated_prefix(monkeypatch):
    from agent_integrations.ag_ui.projection import AgUiProjector

    original = AgUiProjector._project_event
    projected = []

    def count(self, event, identity, state):
        projected.append(event.event_id)
        return original(self, event, identity, state)

    monkeypatch.setattr(AgUiProjector, "_project_event", count)
    events = [_entry(0, "run"), *(_entry(index) for index in range(1, 100))]
    list(_project_new_task_events(events, IDENTITY, None))
    assert len(projected) == len(events)


@pytest.mark.parametrize("after_sequence", [None, 20])
def test_stream_preflight_validates_identity_without_projecting_the_backlog(
    monkeypatch, after_sequence, tmp_path
):
    from agent_integrations.ag_ui.projection import AgUiProjector
    from zebra_agent_api import ag_ui_stream

    _, session, start, stores = _checkpoint_backlog(tmp_path)
    events = stores.tasks.read_events(session, -1)  # Fixture oracle, before GET guard.
    tasks = ObservationTasks(stores.tasks)
    stores = replace(stores, tasks=tasks)
    projected = []
    original = AgUiProjector._project_event

    def count(self, event, identity, state):
        projected.append(event.event_id)
        return original(self, event, identity, state)

    monkeypatch.setattr(AgUiProjector, "_project_event", count)
    cursor = (
        None
        if after_sequence is None
        else AgUiCursor(
            thread_id=str(session),
            run_id="run-1",
            sequence=start + after_sequence,
            event_id=str(events[start + after_sequence].event.event_id),
        )
    )
    context = ag_ui_stream.prepare_agui_stream(
        stores,
        f"/agui/threads/{session}/runs/run-1/stream",
        {} if cursor is None else {"cursor": cursor.encode()},
    )
    assert isinstance(context, ag_ui_stream.AgUiStreamContext)
    assert projected == [] and tasks.pages == []
    tasks.allow_bodies = True

    async def consume_first():
        from tests.api.test_agui_stream_routes import _FakeRequest

        stream = ag_ui_stream.tail_agui_events(context, _FakeRequest())
        try:
            first = await anext(stream)
            frame_cursor = AgUiCursor.decode(first.splitlines()[0].removeprefix("id: "))
            eligible = [
                entry.event.event_id
                for entry in events
                if start <= entry.task_sequence <= frame_cursor.sequence
            ]
            if cursor is not None:
                eligible = [
                    entry.event.event_id
                    for entry in events
                    if cursor.sequence < entry.task_sequence <= frame_cursor.sequence
                ]
            assert projected == eligible
            assert len(projected) <= 2  # No checkpoint prefix/body hydration for warm state.
        finally:
            await stream.aclose()

    asyncio.run(consume_first())
    assert len(tasks.pages) == 1


def test_frame_preflight_projects_only_through_its_anchor_and_preserves_recovery_cursor(
    monkeypatch,
    tmp_path,
):
    from agent_integrations.ag_ui.projection import AgUiProjector
    from zebra_agent_api import ag_ui_stream

    _, session, start, stores = _checkpoint_backlog(tmp_path)
    events = stores.tasks.read_events(session, -1)
    from agent_integrations.ag_ui import AgUiRunIdentity

    identity = AgUiRunIdentity(session_id=session, thread_id=str(session), run_id="run-1")
    cursor = list(_project_new_task_events(events, identity, None))[2][0]
    tasks = ObservationTasks(stores.tasks)
    stores = replace(stores, tasks=tasks)
    projected = []
    original = AgUiProjector._project_event

    def count(self, event, identity, state):
        projected.append(event.event_id)
        return original(self, event, identity, state)

    monkeypatch.setattr(AgUiProjector, "_project_event", count)
    path = f"/agui/threads/{session}/runs/run-1/stream"
    context = ag_ui_stream.prepare_agui_stream(stores, path, {"cursor": cursor.encode()})
    assert isinstance(context, ag_ui_stream.AgUiStreamContext)
    assert projected == [] and tasks.pages == []
    forged = cursor.model_copy(update={"frame_index": 99})
    rejected = ag_ui_stream.prepare_agui_stream(stores, path, {"cursor": forged.encode()})
    assert rejected.status_code == 400
    recovered = AgUiCursor.decode(rejected.body["recovery_cursor"])
    assert recovered.sequence == start + 99 and recovered.frame_index == 2
    assert projected == [] and tasks.pages == []


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


def test_internal_client_effect_resume_continues_original_run_through_terminal() -> None:
    wakeup = _entry(
        2,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        payload={
            "kind": "resume",
            "idempotency_key": "client-effect-resume:effect-1",
            "payload": {"client_effect_result": {"status": "succeeded"}},
        },
    )
    wakeup = replace(wakeup, event=wakeup.event.model_copy(update={"actor": EventActor.HARNESS}))
    terminal = _entry(3, event_type=EventType.TURN_COMPLETED, payload={})
    events = [_entry(0, "run"), _entry(1), wakeup, terminal]

    binding = bind_task_run(events, "run-1")

    assert binding.stop is None
    assert binding.includes(terminal)
    assert _has_run_terminal_event(events, "run-1")
    assert any(
        event.type == "RUN_FINISHED"
        for event in AgUiTaskProjector().project_task(events, IDENTITY).events
    )


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


def test_preflight_rejects_non_increasing_canonical_segment_without_content_projection():
    events = [_entry(0, "run"), _entry(1)]
    events[1] = replace(
        events[1], segment_sequence=0, event=events[1].event.model_copy(update={"sequence": 0})
    )
    with pytest.raises(AgUiProjectionError, match="increasing"):
        AgUiTaskProjector().validate_task_cursor(events, IDENTITY)


@pytest.mark.parametrize("reconnect", [False, True])
def test_durable_failure_has_no_sse_id_and_does_not_write_events(tmp_path, reconnect):
    from agent_storage import SQLiteEventStore
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
        checkpoint_stores(path, session, "failing"),
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
    errors = [frame for frame in frames if "zebra.observation.problem" in frame]
    assert len(errors) == 1 and not errors[0].startswith("id:")
    assert "command_requires_reconciliation" in errors[0]
    assert '"retryable":false' in errors[0] and '"type":"CUSTOM"' in errors[0]
    assert not any("RUN_ERROR" in frame for frame in frames)
    assert calls[0][2] == accepted.event_id
    assert store.list_for_session(session) == before
    assert context.cursor == (cursor if reconnect else None)


def test_reconnect_accepts_exact_unindexed_tail_cursor(tmp_path):
    from agent_storage import SQLiteEventStore, sqlite_control_plane_stores
    from agent_storage.database import SQLiteDatabase
    from zebra_agent_api.ag_ui_stream import AgUiStreamContext, prepare_agui_stream

    from tests.api.test_agui_stream_routes import (
        _append,
        _seed_ready_session,
        _stream_path,
    )

    path, session, sequence = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    event = _append(
        SQLiteEventStore(path),
        session,
        sequence,
        EventType.MODEL_RESPONSE_RECEIVED,
        {"model_call_id": "tail", "assistant_message": "tail"},
    )
    checkpoint_stores(path, session, "legacy")
    # Source coordinates are authoritative even when the derived index has a hole.
    with SQLiteDatabase(path).connect() as connection:
        connection.execute("DELETE FROM task_event_index WHERE event_id=?", (str(event.event_id),))
    cursor = AgUiCursor(
        thread_id=str(session), run_id="legacy", sequence=sequence, event_id=str(event.event_id)
    )
    result = prepare_agui_stream(
        stores, _stream_path(session, "legacy"), {"cursor": cursor.encode()}
    )
    assert isinstance(result, AgUiStreamContext)


def test_steady_poll_does_not_reload_task_history_or_all_members(tmp_path, monkeypatch):
    from agent_core.domain.identifiers import TaskId
    from agent_storage import SQLiteEventStore
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
    stores = checkpoint_stores(path, session, "bounded")

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
    assert tasks.histories == tasks.memberships == 0


def test_slow_outcome_cannot_emit_after_authorization_expiry(tmp_path):
    from datetime import UTC, datetime, timedelta
    from time import sleep

    from agent_storage import SQLiteEventStore
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
        checkpoint_stores(path, session, "slow"),
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
    assert not any("RUN_ERROR" in frame or "zebra.observation.problem" in frame for frame in frames)


def test_consumer_pause_past_deadline_stops_before_resuming_projection(tmp_path):
    from datetime import UTC, datetime, timedelta

    from zebra_agent_api.ag_ui_stream import prepare_agui_stream, tail_agui_events

    from tests.api.test_agui_stream_routes import _FakeRequest, _seed_ready_session, _stream_path

    path, session, _ = _seed_ready_session(tmp_path)
    context = prepare_agui_stream(
        checkpoint_stores(path, session, "local"), _stream_path(session, "local"), {}
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
