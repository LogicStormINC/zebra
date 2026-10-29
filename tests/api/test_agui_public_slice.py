"""Native public successor resolution and tail boundaries on SQLite and PostgreSQL."""

import asyncio
import json
from dataclasses import replace
from time import monotonic

import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import (
    CheckpointNotReady,
    ProjectionScope,
)
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.ag_ui.standard_projection import StandardAgUiProjector
from agent_integrations.ag_ui.standard_state import StandardProjectionState
from zebra_agent_api.ag_ui_checkpoint_tail import tail_checkpoint_frames
from zebra_agent_api.ag_ui_public_binding import resolve_public_slice
from zebra_agent_api.ag_ui_stream import AgUiStreamContext

from tests.agent_integrations import test_ag_ui_binding_persistence as persistence
from tests.agent_integrations.binding_store_cases import (
    append,
    ready,
    resolve,
)
from tests.agent_integrations.binding_store_cases import (
    root as original_root,
)

metadata_dsn = persistence.metadata_dsn
native = persistence.stores
PROFILE = AgUiProjectionProfile(
    "agui-standard-1.0", StandardAgUiProjector(), state_type=StandardProjectionState
)


def root(stores):
    segment = original_root(stores)
    append(
        stores, segment, 2, EventType.TASK_PREPARED, {"title": "fixture", "user_input": "fixture"}
    )
    append(stores, segment, 3, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    return segment


def resume(stores, segment, seq):
    from uuid import uuid4

    command = SessionCommand(
        command_id=uuid4(),
        session_id=segment,
        kind=SessionCommandKind.RESUME,
        expected_revision=seq - 1,
        idempotency_key=f"approval-resume:public-slice-{seq}",
        payload={},
    )
    return append(stores, segment, seq, EventType.SESSION_COMMAND_ACCEPTED, command.event_payload())


def materialize(stores, segment):
    from agent_core.application.session_projection import rebuild_session

    stores.sessions.save_session(rebuild_session(stores.events.list_for_session(segment)))
    task = TaskId(segment)
    run = ready(stores.tasks, task)
    scope = ProjectionScope(
        stores.namespace, task, run.anchor.event_id, PROFILE.checkpoint_version()
    )
    identity = AgUiRunIdentity(session_id=segment, thread_id=str(task), run_id="run")
    resolve(stores.tasks, run, scope)
    after = stores.tasks.read_checkpoint_head(scope).through_sequence
    while after < run.highwater:
        page = stores.tasks.read_event_page(task, after, limit=256, through_sequence=run.highwater)
        plan = build_projection_page_plan(stores.tasks, page, run, scope, identity, profile=PROFILE)
        transition = AgUiCheckpointMaterializer(stores.tasks, profile=PROFILE).prepare_page(
            page,
            plan,
            scope,
            identity,
        )
        stores.tasks.commit_projection_page(transition)
        after = page.next_sequence
    return run, scope, identity


def binding(stores, segment, sequence):
    return resolve_public_slice(
        stores.tasks,
        namespace=stores.namespace,
        task_id=TaskId(segment),
        internal_run_id="run",
        source=stores.tasks.read_event_header(TaskId(segment), sequence),
        profile=PROFILE,
    )


class Connected:
    async def is_disconnected(self):
        return False


def context(stores, segment, public):
    # The tail accesses native tasks but no sessions/events or execution service.
    from types import SimpleNamespace

    return AgUiStreamContext(
        stores=SimpleNamespace(tasks=stores.cold(), deployment_namespace=None),
        task_id=TaskId(segment),
        identity=AgUiRunIdentity(session_id=segment, thread_id=str(segment), run_id="run"),
        cursor=None,
        deployment_namespace=stores.namespace,
        profile=PROFILE,
        public_slice=public,
        recovery_notice=False,
    )


async def collect(ctx, timeout=3):
    return [
        frame
        async for frame in tail_checkpoint_frames(
            ctx,
            Connected(),
            monotonic() + timeout,
            poll_seconds=0.001,
            keepalive_seconds=10,
        )
    ]


def events(frames):
    return [
        json.loads(line[6:])
        for frame in frames
        for line in frame.splitlines()
        if line.startswith("data: ")
    ]


def test_successor_resolution_reads_exact_after_coordinate_not_future_state(native):
    segment = root(native)
    append(
        native, segment, 4, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}
    )
    materialize(native, segment)
    resume(native, segment, 5)
    run = ready(native.tasks, TaskId(segment))
    with pytest.raises(CheckpointNotReady):
        binding(native, segment, 5)
    materialize(native, segment)
    second = binding(native, segment, 5)
    assert second is not None and not second.turn_finished
    append(native, segment, 6, EventType.SESSION_CANCELLED, {"reason": "cancelled"})
    materialize(native, segment)
    # Exact-after-3 remains open even though the current head is terminal.
    assert binding(native, segment, 5) == second
    first = binding(native, segment, run.start)
    assert first.run_id == second.previous_run_id and first.run_id != second.run_id
    forged = replace(native.tasks.read_event_header(TaskId(segment), 5), segment_sequence=88)
    with pytest.raises(ValueError):
        resolve_public_slice(
            native.tasks,
            namespace=native.namespace,
            task_id=TaskId(segment),
            internal_run_id="run",
            source=forged,
            profile=PROFILE,
        )


def test_old_terminal_does_not_close_open_successor_and_own_terminal_ends(native):
    segment = root(native)
    append(
        native, segment, 4, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}
    )
    materialize(native, segment)
    resume(native, segment, 5)
    _, scope, _ = materialize(native, segment)
    assert native.tasks.read_checkpoint_head(scope).terminal.task_sequence == 4
    second = binding(native, segment, 5)
    assert second is not None
    ctx = context(native, segment, second)

    async def exercise():
        tail = tail_checkpoint_frames(
            ctx, Connected(), monotonic() + 3, poll_seconds=0.001, keepalive_seconds=10
        )
        try:
            initial = []
            while len(events(initial)) < 2:
                initial.append(await anext(tail))
            pending = asyncio.create_task(anext(tail))
            await asyncio.sleep(0.08)
            # A retained terminal from slice 1 must leave slice 2 open.
            assert not pending.done()
            append(native, segment, 6, EventType.SESSION_CANCELLED, {"reason": "cancelled"})
            materialize(native, segment)
            initial.append(await asyncio.wait_for(pending, 2))
            async for frame in tail:
                initial.append(frame)
            return events(initial)
        finally:
            await tail.aclose()

    received = asyncio.run(exercise())
    assert received[0]["type"] == "RUN_STARTED" and received[0]["runId"] == second.run_id
    assert received[-1]["type"] == "RUN_FINISHED"
    assert not any(e.get("name", "").startswith("zebra.stream") for e in received)


def test_terminal_and_next_start_same_page_stop_at_requested_slice(native):
    segment = root(native)
    append(
        native, segment, 4, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}
    )
    resume(native, segment, 5)
    append(
        native, segment, 6, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}
    )
    resume(native, segment, 7)
    append(native, segment, 8, EventType.SESSION_CANCELLED, {"reason": "cancelled"})
    materialize(native, segment)
    second = binding(native, segment, 5)
    third = binding(native, segment, 7)
    assert second is not None and third is not None and second.run_id != third.run_id
    received = events(
        asyncio.run(collect(replace(context(native, segment, second), recovery_notice=True)))
    )
    assert [e["runId"] for e in received if e["type"] == "RUN_STARTED"] == [second.run_id]
    assert received[-1]["type"] == "RUN_ERROR"  # No runId on a suspended slice error.
    assert third.run_id not in str(received)


def test_waiting_children_continuation_and_ignored_late_intent_have_no_new_slice(native):
    segment = root(native)
    append(native, segment, 4, EventType.SESSION_SUSPENDED, {"reason": "waiting_children"})
    resume(native, segment, 5)
    append(native, segment, 6, EventType.SESSION_CANCELLED, {"reason": "cancelled"})
    resume(native, segment, 7)
    materialize(native, segment)
    assert binding(native, segment, 5) is None
    assert binding(native, segment, 7) is None
