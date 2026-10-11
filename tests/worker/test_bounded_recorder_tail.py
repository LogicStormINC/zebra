"""Canonical native tails never hydrate the unrelated historical prefix."""

import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres.task_io import TaskIoConnection, task_io_deadline
from agent_storage.postgres.worker_replay_reader import PostgresWorkerReplayReader
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder

from tests.worker.test_bounded_session_recovery import NS, seed
from tests.worker.test_bounded_session_recovery import native as native_fixture

native = native_fixture


def recorder(state, after, read):
    return DurableHarnessEventRecorder(
        session=state.bootstrap.session.model_copy(update={"current_sequence": after}),
        workspace=rebuild_workspace(list(state.bootstrap.events)).model_copy(
            update={"current_sequence": after}
        ),
        event_store=Mock(read_since=Mock(side_effect=AssertionError("whole-history tail"))),
        projection_store=Mock(),
        workspace_store=Mock(),
        model_call_indexer=Mock(),
        tool_run_indexer=Mock(),
        worker_projection_transaction=Mock(
            project_persisted_worker_event=Mock(
                side_effect=lambda event, session, workspace, **kw: SimpleNamespace(
                    event=event, session=session, workspace=workspace
                )
            )
        ),
        worker_mutation_authority=state.authority.model_copy(
            update={"expected_stream_revision": after}
        ),
        tail_reader=read,
    )


@pytest.mark.parametrize("size", [1_000, 10_000, 100_000])
def test_native_refresh_seeks_only_two_event_tail(native, size):
    state = seed(native, size)
    reader = PostgresWorkerReplayReader(native, deployment_namespace=NS)
    pages = []

    def read(authority, through):
        page = reader.tail_page(authority, through)
        pages.append(page)
        return page

    target = recorder(state, size - 3, read)
    target.refresh_tail()
    assert [len(page.events) for page in pages] == [2]
    assert target.session.current_sequence == size - 1
    assert target.workspace.current_sequence == size - 1
    assert target.worker_mutation_authority.expected_stream_revision == size - 1
    assert target.events == ()
    target._projection_store.save_session.assert_not_called()
    target._model_call_indexer.index_worker_event.assert_not_called()


@pytest.mark.parametrize("project", [False, True])
def test_native_tail_frozen_head_and_same_fence_across_pages(native, project):
    state = seed(native, 1_000)
    reader = PostgresWorkerReplayReader(native, deployment_namespace=NS)
    pages = []
    fences = []

    def read(authority, through):
        page = reader.tail_page(authority, through)
        pages.append(page)
        fences.append(authority.lease_fence)
        if len(pages) == 1:
            state.events.append(
                SessionEvent.create(
                    session_id=state.session_id,
                    sequence=1_000,
                    event_type=EventType.RUNTIME_CLEANUP_FAILED,
                    actor=EventActor.SYSTEM,
                    payload={"target": "runtime", "error_type": "probe", "attempt_number": 1},
                )
            )
        return page

    target = recorder(state, 3, read)
    consume = target.project_persisted_tail if project else target.refresh_tail
    consume()
    assert [page.after_sequence for page in pages] == [3, 259, 515, 771]
    assert all(page.highwater == 999 and len(page.events) <= 256 for page in pages)
    assert all(fence == state.lease.fence for fence in fences)
    assert target.session.current_sequence == 999
    assert len(target.events) == (996 if project else 0)
    consume()
    assert target.session.current_sequence == 1_000
    assert pages[-1].after_sequence == 999
    assert pages[-1].highwater == 1_000


def test_native_tail_rechecks_released_fence_before_next_page(native):
    state = seed(native, 600)
    reader = PostgresWorkerReplayReader(native, deployment_namespace=NS)
    calls = 0

    def read(authority, through):
        nonlocal calls
        calls += 1
        page = reader.tail_page(authority, through)
        if calls == 1:
            state.leases.release(state.session_id, fence=state.lease.fence)
        return page

    target = recorder(state, 3, read)
    with pytest.raises(LeaseLostError):
        target.refresh_tail()
    assert calls == 2
    assert target.session.current_sequence == 259


@pytest.mark.parametrize("project", [False, True])
@pytest.mark.parametrize("outer", [False, True])
def test_native_tail_cumulative_deadline_resumes_same_captured_head(
    native, monkeypatch, project, outer
):
    state = seed(native, 600)
    reader = PostgresWorkerReplayReader(native, deployment_namespace=NS)
    target = recorder(state, 3, reader.tail_page)
    execute = TaskIoConnection.execute
    connections = []

    def slow(connection, query, *args, **kwargs):
        if isinstance(query, str) and query.startswith("SELECT sequence,event_bytes_bound"):
            connections.append(connection)
            execute(connection, "SELECT pg_sleep(%s)", (0.15 if outer else 1.1,))
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", slow)
    consume = target.project_persisted_tail if project else target.refresh_tail
    started = time.monotonic()
    with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
        with task_io_deadline(started + 0.25) if outer else nullcontext():
            consume()
    assert time.monotonic() - started < (1 if outer else 3)
    assert len(connections) == 2 and all(connection.closed for connection in connections)
    assert target.session.current_sequence == 259
    assert target._tail_highwater == 599
    assert target.worker_mutation_authority.lease_fence == state.lease.fence
    monkeypatch.setattr(TaskIoConnection, "execute", execute)
    consume()
    assert target.session.current_sequence == 599
    assert target._tail_highwater is None
    assert [event.sequence for event in target.events] == (list(range(4, 600)) if project else [])
