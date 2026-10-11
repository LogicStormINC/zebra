"""Native PostgreSQL canonical admission and post-lock fencing on scratch DBs."""

from dataclasses import replace
from datetime import timedelta

import pytest
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointStale
from agent_storage import PostgresLeaseStore
from agent_storage.execution_inputs import ExecutionInputStore
from agent_storage.postgres.database import PostgresDatabase

from tests.agent_storage import test_postgres_task_projection_checkpoints as checkpoint_tests
from tests.agent_storage.test_postgres_worker_progress import NS, seed

native_progress_dsn = checkpoint_tests.checkpoint_dsn


def inputs(dsn):
    tasks, events, scope = seed(dsn)
    database = PostgresDatabase(dsn, deployment_namespace=NS)
    with database.connect_task_io() as connection:
        assert (
            connection.execute(
                "SELECT name FROM zebra_schema_migrations WHERE version=75"
            ).fetchone()["name"]
            == "execution_input_evidence_boundaries"
        )
    lease_store = PostgresLeaseStore(dsn, deployment_namespace=NS)
    lease = lease_store.acquire(
        scope.task_id, owner_instance_id="input-native", ttl=timedelta(seconds=60)
    )
    return ExecutionInputStore(database, tasks, namespace=NS, postgres=True), lease_store, lease


def test_postgres_creation_update_cas_and_stale_fence(native_progress_dsn):
    store, leases, lease = inputs(native_progress_dsn)
    page = store.read_page(lease, -1, 1)
    head = store.advance(lease, page)
    assert head.through_sequence == 1 and len(head.state.events) == 2
    with pytest.raises(CheckpointStale):
        store.advance(lease, page)
    leases.release(lease.session_id, fence=lease.fence)
    with pytest.raises(LeaseLostError):
        store.advance(lease, page)


def test_postgres_page_forgery_and_namespace_conflict(native_progress_dsn):
    store, leases, lease = inputs(native_progress_dsn)
    page = store.read_page(lease, -1, 1)
    entry = replace(
        page.events[0], event=page.events[0].event.model_copy(update={"payload": {"title": "fake"}})
    )
    with pytest.raises(CheckpointConflict):
        store.advance(lease, replace(page, events=(entry, *page.events[1:])))
    assert store.read(lease).through_sequence == -1
    with pytest.raises(ValueError, match="namespace"):
        ExecutionInputStore(store._database, store._tasks, namespace="other", postgres=True)


def test_postgres_expiry_during_head_wait_rolls_back(native_progress_dsn, monkeypatch):
    store, leases, lease = inputs(native_progress_dsn)
    page = store.read_page(lease, -1, 1)
    check = store._fence
    count = 0

    def expire(connection, current):
        nonlocal count
        count += 1
        if count == 2:
            connection.execute(
                "UPDATE worker_leases SET acquired_at=clock_timestamp()-interval '3 seconds', "
                "heartbeat_at=clock_timestamp()-interval '2 seconds', "
                "expires_at=clock_timestamp()-interval '1 second' "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (NS, current.session_id),
            )
        check(connection, current)

    monkeypatch.setattr(store, "_fence", expire)
    with pytest.raises(LeaseLostError):
        store.advance(lease, page)
    assert store.read(lease).through_sequence == -1


def test_postgres_actual_lock_wait_obeys_cumulative_deadline(native_progress_dsn):
    from time import monotonic

    import psycopg
    from agent_storage.postgres.task_io import task_io_deadline

    store, leases, lease = inputs(native_progress_dsn)
    page = store.read_page(lease, -1, 1)
    with psycopg.connect(native_progress_dsn) as blocking:
        blocking.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"{NS}:{lease.session_id}",)
        )
        started = monotonic()
        with pytest.raises(
            (TimeoutError, psycopg.errors.QueryCanceled, psycopg.errors.LockNotAvailable)
        ):
            with task_io_deadline(started + 0.2):
                store.advance(lease, page)
        assert monotonic() - started < 1
    assert store.read(lease).through_sequence == -1


def test_native_cold_compaction_preserves_fence_source_and_semantic_evidence(native_progress_dsn):
    from agent_storage import PostgresEventStore
    from zebra_agent_worker.execution_input_preparation import recover_execution_tool_output

    from tests.worker.test_execution_input_compaction import closed_history, prepare

    store, leases, lease = inputs(native_progress_dsn)
    source = PostgresEventStore(native_progress_dsn, deployment_namespace=NS)
    output = "Exact native result 中文\n" * 7500
    events = closed_history(lease, models=1050, tools=8, output=output)
    for event in events:
        source.append(event)
    source.list_for_session = lambda *_: pytest.fail("native whole-history hydration")
    exact = prepare(store, store._tasks, lease)
    head = store.read(lease)
    assert head.state.evidence.model_request_count == 1050
    assert head.state.evidence.model_response_count == 1050
    assert len(head.state.evidence.tools) == 8
    assert len(exact) < 20 and head.through_sequence == events[-1].sequence
    assert len(head.state.encoded().encode()) < 1_048_576
    current = leases.get(lease.session_id)
    assert current.fence == lease.fence
    assert (
        recover_execution_tool_output(
            store=store,
            lease=lease,
            receipt=head.state.evidence.tools[-1],
            ownership_check=lambda: None,
        )
        == output
    )
    with store._database.connect_task_io() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM session_events WHERE deployment_namespace=%s "
            "AND session_id=%s",
            (NS, lease.session_id),
        ).fetchone()["count"]
        plan = connection.execute(
            "EXPLAIN SELECT task_sequence FROM session_events WHERE deployment_namespace=%s "
            "AND task_id=%s AND session_id=%s AND event_type='turn_completed' "
            "AND replay_command_kind IS NULL AND task_sequence<=%s "
            "ORDER BY task_sequence DESC LIMIT 1",
            (
                NS,
                store._tasks.task_id_for_session(lease.session_id),
                lease.session_id,
                events[-1].sequence,
            ),
        ).fetchall()
    assert count == len(events) + 2
    assert "Index" in str(plan) and "Seq Scan" not in str(plan)


def test_native_missing_compaction_index_is_dependency_not_progress(native_progress_dsn):
    from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
    from agent_core.ports.worker_preparation import PreparationAdvanced

    store, _, lease = inputs(native_progress_dsn)
    with store._database.connect_task_io() as connection:
        connection.execute("DROP INDEX session_events_execution_evidence_boundary")
    with pytest.raises(CheckpointNotReady) as error:
        store.advance(lease, store.read_page(lease, -1, 1))
    assert not isinstance(error.value, PreparationAdvanced)
    assert store.read(lease).through_sequence == -1


def test_native_approval_rehydrates_only_referenced_exchange(native_progress_dsn, monkeypatch):
    from agent_core.domain.events import EventType
    from agent_core.domain.identifiers import new_event_id
    from agent_storage import PostgresEventStore

    from tests.worker.test_execution_input_compaction import closed_history, prepare

    store, _, lease = inputs(native_progress_dsn)
    source = PostgresEventStore(native_progress_dsn, deployment_namespace=NS)
    history = closed_history(lease, tools=3)
    for event in history:
        source.append(event)
    prepare(store, store._tasks, lease)
    before = store.read(lease)
    approval = history[-1].model_copy(
        update={
            "event_id": new_event_id(),
            "sequence": history[-1].sequence + 1,
            "event_type": EventType.APPROVAL_REQUESTED,
            "payload": {"tool_call_id": "tool:1"},
        }
    )
    source.append(approval)
    fence = store._fence
    checks = 0

    def reject_after_rehydration(connection, current):
        nonlocal checks
        checks += 1
        fence(connection, current)
        if checks == 2:
            raise LeaseLostError("post-read fence was lost")

    monkeypatch.setattr(store, "_fence", reject_after_rehydration)
    with pytest.raises(LeaseLostError):
        prepare(store, store._tasks, lease)
    assert store.read(lease) == before  # Restored bodies and frontier commit together.
    monkeypatch.setattr(store, "_fence", fence)
    source.list_for_session = lambda *_: pytest.fail("whole-history approval rehydration")
    exact = prepare(store, store._tasks, lease)
    assert approval in exact
    assert all(event in exact for event in history if event.payload.get("tool_call_id") == "tool:1")
    evidence = store.read(lease).state.evidence
    assert tuple(tool.call_id for tool in evidence.tools) == ("tool:0", "tool:2")
    assert evidence.archived_event_count == 6
