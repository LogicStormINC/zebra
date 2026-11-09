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

from tests.agent_storage.test_postgres_task_projection_checkpoints import (
    checkpoint_dsn as full_schema,
)
from tests.worker.test_bounded_session_recovery import NS, seed
from tests.worker.test_bounded_session_recovery import native as native_fixture

native = native_fixture
checkpoint_dsn = full_schema


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


def test_prepare_checks_ownership_once_before_bounded_tail(checkpoint_dsn):
    state = seed(checkpoint_dsn, 10)
    reader = PostgresWorkerReplayReader(checkpoint_dsn, deployment_namespace=NS)
    read = Mock(wraps=reader.tail_page)
    target = recorder(state, 9, read)

    def check():
        lease = state.leases.get(state.session_id)
        if lease is None or lease.fence != state.lease.fence:
            raise LeaseLostError("ownership revoked")

    target._ownership_check = Mock(side_effect=check)
    args = (EventType.RUNTIME_CLEANUP_FAILED, EventActor.SYSTEM,
            {"target": "runtime", "error_type": "probe", "attempt_number": 1})
    prepared = target.prepare(*args)
    assert prepared.sequence == 10
    target._ownership_check.assert_called_once()
    read.assert_called_once()

    state.leases.release(state.session_id, fence=state.lease.fence)
    with pytest.raises(LeaseLostError, match="ownership revoked"):
        target.append_event(prepared)
    target._worker_projection_transaction.commit_worker_event.assert_not_called()
    assert target.session.current_sequence == 9
    with pytest.raises(LeaseLostError, match="ownership revoked"):
        target.prepare(*args)
    read.assert_called_once()


@pytest.mark.parametrize("isolation", ["default", "serializable"])
def test_tail_read_is_read_only_without_transaction_id(checkpoint_dsn, monkeypatch, isolation):
    from agent_storage.postgres import worker_replay_reader

    state = seed(checkpoint_dsn, 10)
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(checkpoint_dsn)
    dsn = checkpoint_dsn if isolation == "default" else make_conninfo(
        checkpoint_dsn,
        options=params.get("options", "") + " -c default_transaction_isolation=serializable",
    )
    reader = PostgresWorkerReplayReader(dsn, deployment_namespace=NS)
    original = worker_replay_reader.read_session_page
    observed = []

    def read(connection, *args, **kwargs):
        row = connection.execute(
            "SELECT current_setting('transaction_read_only') AS readonly, "
            "current_setting('transaction_isolation') AS isolation, "
            "pg_current_xact_id_if_assigned() AS xid"
        ).fetchone()
        observed.append(row)
        assert (row["readonly"], row["isolation"], row["xid"]) == (
            "on", "read committed", None
        )
        return original(connection, *args, **kwargs)

    monkeypatch.setattr(worker_replay_reader, "read_session_page", read)
    assert reader.tail_page(state.authority).highwater == 9
    assert len(observed) == 1


@pytest.mark.parametrize("change", ["release", "epoch", "expiry", "new_owner"])
def test_tail_read_does_not_block_control_and_rejects_changed_fence(
    checkpoint_dsn, monkeypatch, change
):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from uuid import uuid4

    from agent_storage.postgres import worker_replay_reader

    state = seed(checkpoint_dsn, 10)
    reader = PostgresWorkerReplayReader(checkpoint_dsn, deployment_namespace=NS)
    original = worker_replay_reader.read_session_page

    def mutate():
        if change in {"release", "new_owner"}:
            state.leases.release(state.session_id, fence=state.lease.fence)
            if change == "new_owner":
                state.leases.acquire(
                    state.session_id, owner_instance_id="replacement", ttl=timedelta(seconds=30)
                )
        else:
            with psycopg.connect(checkpoint_dsn) as connection:
                if change == "epoch":
                    connection.execute(
                        "UPDATE control_plane_epochs SET epoch=%s WHERE deployment_namespace=%s",
                        (uuid4(), NS),
                    )
                else:
                    connection.execute(
                        "UPDATE worker_leases SET "
                        "acquired_at=clock_timestamp()-interval '3 seconds', "
                        "heartbeat_at=clock_timestamp()-interval '2 seconds', "
                        "expires_at=clock_timestamp()-interval '1 second' "
                        "WHERE deployment_namespace=%s AND session_id=%s",
                        (NS, state.session_id),
                    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        def read(connection, *args, **kwargs):
            page = original(connection, *args, **kwargs)
            pool.submit(mutate).result(timeout=1)  # Control must finish while the read is open.
            return page

        monkeypatch.setattr(worker_replay_reader, "read_session_page", read)
        with pytest.raises(LeaseLostError):
            reader.tail_page(state.authority)


def test_tail_read_rechecks_real_force_stop_after_page(checkpoint_dsn, monkeypatch):
    from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
    from agent_storage import PostgresEventStore
    from agent_storage.postgres import worker_replay_reader
    from zebra_agent_api import RouteAdapter

    from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
    from tests.agent_storage.test_postgres_direct_control_api import _app
    from tests.agent_storage.test_postgres_force_stops import _force
    from tests.agent_storage.test_postgres_runtime_instances import _setup

    lease = _setup(checkpoint_dsn)
    source = PostgresEventStore(checkpoint_dsn, deployment_namespace=NAMESPACE)
    authority = WorkerMutationAuthority(
        deployment_namespace=NAMESPACE, session_id=lease.session_id,
        lease_fence=lease.fence,
        expected_stream_revision=source.read_session_highwater(lease.session_id),
    )
    reader = PostgresWorkerReplayReader(checkpoint_dsn, deployment_namespace=NAMESPACE)
    original = worker_replay_reader.read_session_page

    def read(connection, *args, **kwargs):
        page = original(connection, *args, **kwargs)
        stopped = RouteAdapter(_app(checkpoint_dsn)).handle(_force(lease.session_id))
        assert stopped.status_code == 202
        return page

    monkeypatch.setattr(worker_replay_reader, "read_session_page", read)
    with pytest.raises(LeaseLostError):
        reader.tail_page(authority)
