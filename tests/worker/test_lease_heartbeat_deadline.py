"""Native renewal cancellation and bounded ownership/cleanup admission."""

import time
from datetime import UTC, datetime, timedelta
from threading import Event, Timer
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_storage.leases import SQLiteLeaseStore
from agent_storage.postgres.leases import PostgresLeaseStore
from agent_storage.postgres.task_io import (
    TaskIoConnection,
    current_task_io_deadline,
    task_io_deadline,
)
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat, LeaseHeartbeatError

from tests.worker.test_bounded_session_recovery import NS, seed, service
from tests.worker.test_bounded_session_recovery import native as native_fixture

native = native_fixture


def test_native_claims_release_sql_has_its_own_deadline_without_heartbeat(native, monkeypatch):
    state = seed(native, count=3)
    # Real, composed adapter, not Mock(spec=PostgresLeaseStore): mocks can spoof
    # isinstance without possessing the native database/driver contract.
    options = conninfo_to_dict(native)["options"] + " -c statement_timeout=3000"
    store = PostgresLeaseStore(make_conninfo(native, options=options), deployment_namespace=NS)
    claims = SessionClaimService(store, service(state))
    connections, deadlines, pids = [], [], []
    connect = store._database.connect

    def observe():
        deadlines.append(current_task_io_deadline())
        connection = connect()
        connections.append(connection)
        pids.append(connection.info.backend_pid)
        return connection

    monkeypatch.setattr(store._database, "connect", observe)
    with psycopg.connect(native) as database:
        database.execute("""CREATE FUNCTION slow_release() RETURNS trigger AS $$ BEGIN
            PERFORM pg_sleep(5); RETURN NEW; END; $$ LANGUAGE plpgsql""")
        database.execute("""CREATE TRIGGER slow_release BEFORE UPDATE ON worker_leases
            FOR EACH ROW EXECUTE FUNCTION slow_release()""")
    try:
        assert current_task_io_deadline() is None
        started = time.monotonic()
        with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
            claims.release_lease(state.lease)
        elapsed = time.monotonic() - started
        # RED bypassing claims._lease_io uses the 3s server safety net, not the
        # 2s native deadline. No test thread cancellation or outer scope helps it.
        assert elapsed < 2.5
        assert len(deadlines) == 1 and deadlines[0] is not None
        assert started < deadlines[0] <= started + 2.1
        assert isinstance(connections[0], TaskIoConnection)
        assert connections[0].closed
        assert current_task_io_deadline() is None
        with psycopg.connect(native) as database:
            assert (
                database.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE pid=%s AND state='active'",
                (pids[0],),
                ).fetchone()[0]
                == 0
            )
        active = state.leases.get(state.session_id)
        assert active is not None
        assert active.fence == state.lease.fence
        assert active.checkpoint == state.lease.checkpoint
    finally:
        with psycopg.connect(native) as database:
            database.execute("DROP TRIGGER slow_release ON worker_leases")
        monkeypatch.setattr(store._database, "connect", connect)
        claims.release_lease(state.lease)


def lease():
    now = datetime.now(UTC)
    return WorkerLease(
        session_id=uuid4(),
        fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="hb"),
        checkpoint=0,
        acquired_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=30),
    )


def test_lock_admission_and_exit_do_not_wait_for_an_uncooperative_port():
    entered, unblock = Event(), Event()
    claims = Mock()

    def blocked(current, **kwargs):
        assert current_task_io_deadline() is not None
        entered.set()
        assert unblock.wait(2)
        return current

    claims.heartbeat_lease.side_effect = blocked
    heartbeat = LeaseHeartbeat(claims, lease(), lease_ttl_seconds=30)
    heartbeat._io_seconds = 0.05
    heartbeat._interval_seconds = 0.001
    try:
        heartbeat.__enter__()
        assert entered.wait(1)
        started = time.monotonic()
        with pytest.raises(LeaseHeartbeatError, match="lock deadline"):
            heartbeat.require_owned()
        assert time.monotonic() - started < 0.3
        started = time.monotonic()
        with pytest.raises(LeaseHeartbeatError, match="did not stop"):
            heartbeat.__exit__(None, None, None)
        assert time.monotonic() - started < 0.5
        # A timeout never claims to have killed an arbitrary Port/thread, and
        # never releases a fence while its outstanding renewal could still write.
        claims.release_lease.assert_not_called()
    finally:
        unblock.set()
        heartbeat._thread.join(1)
    assert not heartbeat._thread.is_alive()


def test_native_scope_includes_checkpoint_and_release_and_respects_outer_deadline():
    claims = Mock()
    observed = []

    def renew(current, **kwargs):
        observed.append(current_task_io_deadline())
        return current.model_copy(update={"checkpoint": kwargs["checkpoint"]})

    claims.heartbeat_lease.side_effect = renew
    claims.release_lease.side_effect = lambda current: observed.append(current_task_io_deadline())
    outer = time.monotonic() + 0.5
    with task_io_deadline(outer):
        with LeaseHeartbeat(claims, lease(), lease_ttl_seconds=30) as heartbeat:
            assert heartbeat.advance_checkpoint(123).checkpoint == 123
    assert len(observed) == 2
    assert all(value == outer for value in observed)
    assert current_task_io_deadline() is None


def test_sqlite_keeps_unscoped_local_behavior():
    claims = Mock()
    claims._lease_store = Mock(spec=SQLiteLeaseStore)
    claims.heartbeat_lease.side_effect = lambda current, **kwargs: current
    with LeaseHeartbeat(claims, lease(), lease_ttl_seconds=30) as heartbeat:
        assert not heartbeat._bounded_io
        heartbeat.advance_checkpoint(1)
        assert current_task_io_deadline() is None
    claims.release_lease.assert_called_once()


@pytest.mark.parametrize("operation", ["background", "checkpoint", "release"])
def test_native_row_lock_cancels_database_io_and_reaps_thread(native, operation):
    state = seed(native, count=3)
    claims = SessionClaimService(state.leases, service(state))
    heartbeat = LeaseHeartbeat(
        claims, state.lease, lease_ttl_seconds=30, release_on_exit=operation == "release"
    )
    heartbeat._io_seconds = 0.3
    heartbeat._interval_seconds = 0.01 if operation == "background" else 30
    with psycopg.connect(native) as blocker:
        blocker.execute(
            "SELECT 1 FROM worker_leases WHERE deployment_namespace=%s "
            "AND session_id=%s FOR UPDATE",
            (NS, state.session_id),
        )
        started = time.monotonic()
        with pytest.raises((LeaseHeartbeatError, TimeoutError, psycopg.errors.LockNotAvailable)):
            with heartbeat:
                if operation == "background":
                    assert heartbeat._stop.wait(1)
                    heartbeat.require_owned()
                elif operation == "checkpoint":
                    heartbeat.advance_checkpoint(99)
        assert time.monotonic() - started < 1
        assert not heartbeat._thread.is_alive()
    active = state.leases.get(state.session_id)
    assert active is not None
    assert active.fence == state.lease.fence
    assert active.checkpoint == state.lease.checkpoint
    assert active.heartbeat_at == state.lease.heartbeat_at
    claims.release_lease(state.lease)


def test_native_slow_statement_is_cancelled_on_server_not_abandoned(native):
    state = seed(native, count=3)
    claims = SessionClaimService(state.leases, service(state))
    entered = Event()
    pids = []

    def slow(current, **kwargs):
        with state.leases._database.connect() as connection:
            pids.append(connection.info.backend_pid)
            entered.set()
            connection.execute("SELECT pg_sleep(5)")
        pytest.fail("deadline did not cancel the actual PostgreSQL statement")

    claims.heartbeat_lease = slow
    heartbeat = LeaseHeartbeat(claims, state.lease, lease_ttl_seconds=30, release_on_exit=False)
    heartbeat._io_seconds = 0.2
    heartbeat._interval_seconds = 0.001
    started = time.monotonic()
    with pytest.raises(LeaseHeartbeatError):
        with heartbeat:
            assert entered.wait(1)
            assert heartbeat._stop.wait(1)
            heartbeat.require_owned()
    assert time.monotonic() - started < 1
    assert not heartbeat._thread.is_alive()
    assert isinstance(heartbeat._failure, TimeoutError | psycopg.errors.QueryCanceled)
    with psycopg.connect(native) as observer:
        assert (
            observer.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE pid=%s AND state='active'", (pids[0],)
            ).fetchone()[0]
            == 0
        )
    claims.release_lease(state.lease)


def test_native_short_recovery_lock_retries_one_budget_and_keeps_checkpoint(native):
    state = seed(native, count=3)
    claims = SessionClaimService(state.leases, service(state))
    attempts = []
    renew = claims.heartbeat_lease

    def observe(current, **kwargs):
        attempts.append((current.fence, current_task_io_deadline(), kwargs["checkpoint"]))
        return renew(current, **kwargs)

    claims.heartbeat_lease = observe
    heartbeat = LeaseHeartbeat(claims, state.lease, lease_ttl_seconds=30, release_on_exit=False)
    heartbeat._io_seconds = 0.5
    with psycopg.connect(native) as blocker:
        blocker.execute(
            "SELECT 1 FROM worker_leases WHERE deployment_namespace=%s "
            "AND session_id=%s FOR UPDATE",
            (NS, state.session_id),
        )
        unlock = Timer(0.12, blocker.rollback)
        unlock.start()
        try:
            with heartbeat:
                updated = heartbeat.advance_checkpoint(44)
                assert updated.fence == state.lease.fence
                assert updated.checkpoint == 44
                prefix_attempts = list(attempts)
                assert len(prefix_attempts) >= 2
                assert len({deadline for _, deadline, _ in prefix_attempts}) == 1
                assert all(fence == state.lease.fence for fence, _, _ in prefix_attempts)
                assert heartbeat._renew(background=True).checkpoint == 44
                heartbeat.require_owned()
        finally:
            unlock.join(1)
    assert not heartbeat._thread.is_alive()
    assert state.leases.get(state.session_id).checkpoint == 44
    claims.release_lease(updated)
