"""Lease validity must use the DB clock sampled after observable lock waits."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseCheckpointRegressionError, LeaseLostError
from agent_core.domain.sessions import Session
from agent_storage import (
    PostgresLeaseStore,
    bootstrap_control_plane_epoch,
    rotate_control_plane_epoch,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import (
    _lease_from_row,
    _lock_lease_and_clock,
    assert_current_lease_fence,
    lock_session_lease_boundary,
)
from agent_storage.postgres.projections import save_session_in_transaction
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _postgres_dsn_fixture
from tests.agent_storage.test_postgres_leases import _expire

dsn = _dsn_fixture
postgres_dsn = _postgres_dsn_fixture


@pytest.mark.parametrize("month,day", [(3, 8), (11, 1)])
def test_post_lock_clock_normalizes_dst_before_ttl_arithmetic(month, day):
    local = datetime(2026, month, day, 1, 30, tzinfo=ZoneInfo("America/New_York"))

    class Connection:
        def execute(self, query, parameters=None):
            self.is_clock = isinstance(query, str) and "clock_timestamp" in query
            return self

        def fetchone(self):
            return {"now": local} if self.is_clock else None

    _, now = _lock_lease_and_clock(Connection(), "test", uuid4(), update=True)
    ttl = timedelta(hours=2)
    assert now.tzinfo is UTC
    assert (now + ttl).timestamp() - local.timestamp() == ttl.total_seconds()


def test_pg_row_adapter_preserves_fall_back_instants_in_lease_model():
    timezone = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, 1, 50, tzinfo=timezone, fold=0)
    end = datetime(2026, 11, 1, 1, 10, tzinfo=timezone, fold=1)
    lease = _lease_from_row({
        "session_id": uuid4(), "control_plane_epoch": uuid4(), "fencing_token": 1,
        "owner_instance_id": "test", "checkpoint": 0, "acquired_at": start,
        "heartbeat_at": start, "expires_at": end,
    })
    assert lease.expires_at - lease.acquired_at == timedelta(minutes=20)
    assert lease.acquired_at.tzinfo is lease.heartbeat_at.tzinfo is lease.expires_at.tzinfo is UTC


@pytest.fixture
def namespace(dsn):
    name = f"clock-{uuid4()}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=name)
    return name


def _worker_dsn(dsn, name):
    options = conninfo_to_dict(dsn).get("options", "")
    return make_conninfo(dsn, application_name=name, options=f"{options} -c statement_timeout=5000")


def _wait(observer, query, parameters, *, timeout=4):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if observer.execute(query, parameters).fetchone()[0]:
            return
        sleep(0.01)
    raise AssertionError("expected database clock/lock condition was not reached")


def _wait_locked(observer, name):
    _wait(observer, "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
          "WHERE application_name = %s AND wait_event_type = 'Lock')", (name,))


def _row_lock(connection, namespace, session_id):
    connection.execute(
        "SELECT session_id FROM worker_leases "
        "WHERE deployment_namespace = %s AND session_id = %s FOR UPDATE",
        (namespace, session_id),
    ).fetchone()


@pytest.mark.parametrize("action", ["heartbeat", "release", "assert"])
def test_fence_rejected_after_unchanged_row_lock_crosses_expiry(dsn, namespace, action):
    session = Session.create(title="must roll back")
    store = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    lease = store.acquire(session.session_id, owner_instance_id="same-worker",
                          ttl=timedelta(seconds=2), checkpoint=7)
    name = f"lease-clock-{uuid4()}"
    worker_dsn = _worker_dsn(dsn, name)
    worker_store = PostgresLeaseStore(worker_dsn, deployment_namespace=namespace)

    def mutate():
        if action == "heartbeat":
            return worker_store.heartbeat(session.session_id, fence=lease.fence,
                                          ttl=timedelta(seconds=30), checkpoint=8)
        if action == "release":
            return worker_store.release(session.session_id, fence=lease.fence)
        with PostgresDatabase(worker_dsn, deployment_namespace=namespace).connect() as connection:
            # Prove the entire caller transaction rolls back on a failed guard.
            event = SessionEvent.create(session_id=session.session_id, sequence=0,
                                        event_type=EventType.SESSION_CREATED,
                                        actor=EventActor.USER, payload={"title": session.title})
            append_event_in_transaction(connection, namespace, event)
            save_session_in_transaction(connection, namespace, session)
            assert_current_lease_fence(connection, namespace, session.session_id, lease.fence)
        return None

    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with psycopg.connect(dsn) as blocker:
                _row_lock(blocker, namespace, session.session_id)
                future = executor.submit(mutate)
                _wait_locked(observer, name)
                assert observer.execute("SELECT clock_timestamp() < %s",
                                        (lease.expires_at,)).fetchone()[0]
                _wait(observer, "SELECT clock_timestamp() > %s", (lease.expires_at,))
            with pytest.raises(LeaseLostError):
                future.result(timeout=3)
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT expires_at, checkpoint, released_at FROM worker_leases "
            "WHERE deployment_namespace = %s AND session_id = %s",
            (namespace, session.session_id),
        ).fetchone() == (lease.expires_at, 7, None)
        for table in ("session_events", "session_projections"):
            assert connection.execute(
                psycopg.sql.SQL("SELECT count(*) FROM {} WHERE deployment_namespace = %s").format(
                    psycopg.sql.Identifier(table)), (namespace,),
            ).fetchone() == (0,)
    assert store.get(session.session_id) is None


@pytest.mark.parametrize("boundary", ["advisory", "epoch", "row", "advisory_absent"])
def test_acquire_gets_full_ttl_after_each_lock_boundary(dsn, namespace, boundary):
    session = Session.create(title="lock boundary")
    store = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    if boundary != "advisory_absent":
        store.acquire(session.session_id, owner_instance_id="old", ttl=timedelta(seconds=30))
        _expire(dsn, namespace, session.session_id)
    name = f"acquire-clock-{uuid4()}"
    worker = PostgresLeaseStore(_worker_dsn(dsn, name), deployment_namespace=namespace)
    ttl = timedelta(seconds=3)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(dsn, autocommit=True) as observer:
            with psycopg.connect(dsn) as blocker:
                if boundary.startswith("advisory"):
                    lock_session_lease_boundary(blocker, namespace, session.session_id)
                elif boundary == "epoch":
                    blocker.execute("SELECT epoch FROM control_plane_epochs "
                                    "WHERE deployment_namespace = %s FOR UPDATE", (namespace,))
                else:
                    _row_lock(blocker, namespace, session.session_id)
                future = executor.submit(worker.acquire, session.session_id,
                                         owner_instance_id="new", ttl=ttl)
                _wait_locked(observer, name)
                before_release = observer.execute("SELECT clock_timestamp()").fetchone()[0]
            lease = future.result(timeout=3)
    assert lease.acquired_at >= before_release
    assert lease.heartbeat_at == lease.acquired_at
    assert lease.expires_at - lease.acquired_at == ttl
    assert lease.fence.fencing_token == (1 if boundary == "advisory_absent" else 2)


def test_expired_acquire_still_rejects_checkpoint_regression(dsn, namespace):
    session = Session.create(title="checkpoint")
    store = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    first = store.acquire(session.session_id, owner_instance_id="same",
                          ttl=timedelta(seconds=30), checkpoint=7)
    _expire(dsn, namespace, session.session_id)
    with pytest.raises(LeaseCheckpointRegressionError):
        store.acquire(session.session_id, owner_instance_id="same",
                      ttl=timedelta(seconds=30), checkpoint=6)
    next_lease = store.acquire(session.session_id, owner_instance_id="same",
                               ttl=timedelta(seconds=30), checkpoint=7)
    assert next_lease.fence.fencing_token == first.fence.fencing_token + 1
    with PostgresDatabase(dsn, deployment_namespace=namespace).connect() as connection:
        with pytest.raises(LeaseLostError):
            assert_current_lease_fence(connection, namespace, session.session_id, first.fence)
        assert_current_lease_fence(connection, namespace, session.session_id, next_lease.fence)
    beat = store.heartbeat(session.session_id, fence=next_lease.fence,
                           ttl=timedelta(seconds=30), checkpoint=8)
    assert beat.expires_at - beat.heartbeat_at == timedelta(seconds=30)
    with pytest.raises(LeaseCheckpointRegressionError):
        store.heartbeat(session.session_id, fence=beat.fence,
                        ttl=timedelta(seconds=30), checkpoint=7)


@pytest.mark.parametrize("takeover", ["epoch", "successor"])
def test_all_guard_paths_reject_superseded_fence(dsn, namespace, takeover):
    session = Session.create(title="old fence")
    store = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    first = store.acquire(session.session_id, owner_instance_id="old",
                          ttl=timedelta(seconds=30), checkpoint=2)
    if takeover == "epoch":
        rotate_control_plane_epoch(dsn, deployment_namespace=namespace)
    else:
        store.release(session.session_id, fence=first.fence)
    successor = store.acquire(session.session_id, owner_instance_id="new",
                              ttl=timedelta(seconds=30), checkpoint=2)
    with pytest.raises(LeaseLostError):
        store.heartbeat(session.session_id, fence=first.fence,
                        ttl=timedelta(seconds=30), checkpoint=3)
    with pytest.raises(LeaseLostError):
        store.release(session.session_id, fence=first.fence)
    with PostgresDatabase(dsn, deployment_namespace=namespace).connect() as connection:
        with pytest.raises(LeaseLostError):
            assert_current_lease_fence(connection, namespace, session.session_id, first.fence)
        assert_current_lease_fence(connection, namespace, session.session_id, successor.fence)
