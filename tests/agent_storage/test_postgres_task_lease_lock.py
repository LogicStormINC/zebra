"""Fenced rollover serializes the source Session before lease and Task locks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.leases import LeaseConflictError, LeaseLostError
from agent_storage import (
    PostgresAgentTaskConflictError,
    PostgresAgentTaskStore,
    PostgresLeaseStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_index_transactions import attach_segment_for_worker_in_transaction

from tests.agent_storage.test_postgres_agent_tasks import _seed_session, _worker_authority
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_recovery import _rows
from tests.agent_storage.test_postgres_lease_clock import _wait_locked, _worker_dsn

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _setup(dsn, tmp_path, nonroot):
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    root = _seed_session(dsn, NAMESPACE, tmp_path / "root", "Root")
    store = PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE)
    task = store.ensure_for_session(root)
    source = root
    if nonroot:
        source = _seed_session(dsn, NAMESPACE, tmp_path / "source", "Source")
        store.attach_segment_for_worker(
            task.task_id,
            source,
            predecessor_id=root,
            reason=RolloverReason.RECOVERY,
            authority=_worker_authority(dsn, NAMESPACE, root),
        )
    target = _seed_session(dsn, NAMESPACE, tmp_path / "target", "Target")
    return task.task_id, source, target, _worker_authority(dsn, NAMESPACE, source)


def _attach(dsn, task, source, target, authority):
    return PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE).attach_segment_for_worker(
        task, target, predecessor_id=source, reason=RolloverReason.RECOVERY, authority=authority
    )


@pytest.mark.parametrize("nonroot", [False, True])
def test_rollover_and_competing_acquisition_do_not_invert_lease_task_locks(
    dsn,
    tmp_path,
    monkeypatch,
    nonroot,
):
    import agent_storage.postgres.task_index_transactions as transactions

    task, source, target, authority = _setup(dsn, tmp_path, nonroot)
    entered, release = Event(), Event()
    original = transactions.assert_current_lease_fence

    def pause_after_lease(*args):
        original(*args)
        entered.set()
        assert release.wait(4)

    monkeypatch.setattr(transactions, "assert_current_lease_fence", pause_after_lease)
    name = f"task-compete-{uuid4()}"
    competitor = PostgresLeaseStore(_worker_dsn(dsn, name), deployment_namespace=NAMESPACE)
    with ThreadPoolExecutor(max_workers=2) as executor:
        rollover = executor.submit(_attach, dsn, task, source, target, authority)
        try:
            assert entered.wait(3)
            acquisition = executor.submit(
                competitor.acquire, source, owner_instance_id="other", ttl=timedelta(seconds=30)
            )
            with psycopg.connect(dsn, autocommit=True) as observer:
                _wait_locked(observer, name)
                wait = observer.execute(
                    "SELECT wait_event FROM pg_stat_activity WHERE application_name=%s", (name,)
                ).fetchone()
                assert wait == ("advisory",)  # never hold Task/session key while waiting lease
        finally:
            release.set()
        rollover.result(timeout=5)
        with pytest.raises(LeaseConflictError):
            acquisition.result(timeout=5)
    store = PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE)
    assert store.active_segment(task) == target
    assert [segment.session_id for segment in store.segments(task)][-2:] == [source, target]


@pytest.mark.parametrize("nonroot", [False, True])
def test_acquisition_wins_before_rollover_then_old_fence_cannot_mutate_lineage(
    dsn,
    tmp_path,
    nonroot,
):
    from agent_storage.postgres.leases import acquire_lease_in_transaction

    task, source, target, authority = _setup(dsn, tmp_path, nonroot)
    PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).release(
        source, fence=authority.lease_fence
    )
    name = f"task-wait-{uuid4()}"
    before = {
        table: _rows(dsn, table)
        for table in ("agent_tasks", "execution_segments", "task_event_index")
    }
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as owner:
                successor = acquire_lease_in_transaction(
                    owner,
                    NAMESPACE,
                    source,
                    owner_instance_id="successor",
                    ttl=timedelta(seconds=30),
                )
                assert successor.fence.fencing_token > authority.lease_fence.fencing_token
                future = executor.submit(
                    _attach, _worker_dsn(dsn, name), task, source, target, authority
                )
                _wait_locked(observer, name)
            with pytest.raises(LeaseLostError):
                future.result(timeout=5)
    assert before == {table: _rows(dsn, table) for table in before}


@pytest.mark.parametrize("field", ["deployment_namespace", "session_id"])
def test_wrong_authority_rejected_before_session_advisory(dsn, tmp_path, monkeypatch, field):
    import agent_storage.postgres.task_index_transactions as transactions

    task, source, target, authority = _setup(dsn, tmp_path, False)
    wrong = authority.model_copy(
        update={field: "foreign" if field == "deployment_namespace" else uuid4()}
    )

    def forbidden(*args):
        raise AssertionError("wrong identity reached a victim Session lock")

    monkeypatch.setattr(transactions, "lock_session_lease_boundary", forbidden)
    with pytest.raises(LeaseLostError):
        _attach(dsn, task, source, target, wrong)


def test_stale_revision_and_enclosing_rollback_preserve_exact_lineage(dsn, tmp_path):
    task, source, target, authority = _setup(dsn, tmp_path, False)
    tables = ("agent_tasks", "execution_segments", "task_event_index", "worker_leases")
    before = {table: _rows(dsn, table) for table in tables}
    with pytest.raises(PostgresAgentTaskConflictError):
        _attach(
            dsn, task, source, target, authority.model_copy(update={"expected_stream_revision": 0})
        )
    with pytest.raises(RuntimeError, match="injected"):
        with psycopg.connect(dsn) as connection:
            attach_segment_for_worker_in_transaction(
                connection,
                NAMESPACE,
                task_id=task,
                predecessor_id=source,
                segment_id=target,
                reason=RolloverReason.RECOVERY,
                authority=authority,
            )
            raise RuntimeError("injected after lineage write")
    assert before == {table: _rows(dsn, table) for table in tables}
