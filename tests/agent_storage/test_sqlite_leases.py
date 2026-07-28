import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import (
    LeaseCheckpointRegressionError,
    LeaseFence,
    LeaseLostError,
    WorkerLease,
)
from agent_storage import LeaseConflictError, SQLiteLeaseStore


class ManualClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


NOW = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)


def test_lease_domain_rejects_invalid_fence_and_timestamp_order() -> None:
    with pytest.raises(ValueError, match="owner_instance_id"):
        LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=1,
            owner_instance_id=" ",
        )
    with pytest.raises(ValueError, match="acquired_at <= heartbeat_at < expires_at"):
        WorkerLease(
            session_id=new_session_id(),
            fence=LeaseFence(
                control_plane_epoch=uuid4(),
                fencing_token=1,
                owner_instance_id="worker-a",
            ),
            acquired_at=NOW,
            heartbeat_at=NOW + timedelta(seconds=2),
            expires_at=NOW + timedelta(seconds=1),
        )


def test_sqlite_lease_store_acquires_typed_fence_and_reads_active_lease(
    tmp_path: Path,
) -> None:
    store = SQLiteLeaseStore(tmp_path / "leases.db", clock=ManualClock(NOW))
    session_id = new_session_id()

    lease = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
        checkpoint=3,
    )

    assert lease.fence.fencing_token == 1
    assert lease.owner_instance_id == "worker-a"
    assert lease.worker_id == "worker-a"
    assert lease.checkpoint == 3
    assert lease.acquired_at == NOW
    assert store.get(session_id) == lease


@pytest.mark.parametrize("second_owner", ["worker-a", "worker-b"])
def test_sqlite_lease_store_rejects_active_reacquire(
    tmp_path: Path,
    second_owner: str,
) -> None:
    clock = ManualClock(NOW)
    store = SQLiteLeaseStore(tmp_path / "leases.db", clock=clock)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
    )
    clock.advance(seconds=5)

    with pytest.raises(LeaseConflictError, match="active lease"):
        store.acquire(
            session_id,
            owner_instance_id=second_owner,
            ttl=timedelta(seconds=30),
        )

    assert store.get(session_id) == first


def test_active_reacquire_reports_conflict_before_checkpoint_regression(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(tmp_path / "leases.db", clock=ManualClock(NOW))
    session_id = new_session_id()
    store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
        checkpoint=4,
    )

    with pytest.raises(LeaseConflictError, match="active lease"):
        store.acquire(
            session_id,
            owner_instance_id="worker-b",
            ttl=timedelta(seconds=30),
            checkpoint=3,
        )


@pytest.mark.parametrize("owners", [("worker-a", "worker-b"), ("worker-a", "worker-a")])
def test_sqlite_lease_store_allows_only_one_concurrent_acquirer(
    tmp_path: Path,
    owners: tuple[str, str],
) -> None:
    database_path = tmp_path / "leases.db"
    clock = ManualClock(NOW)
    store = SQLiteLeaseStore(database_path, clock=clock)
    session_id = new_session_id()
    start_barrier = Barrier(2)

    def acquire(owner: str) -> WorkerLease | LeaseConflictError:
        start_barrier.wait()
        try:
            return store.acquire(
                session_id,
                owner_instance_id=owner,
                ttl=timedelta(seconds=30),
            )
        except LeaseConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(acquire, owners))

    leases = [result for result in results if isinstance(result, WorkerLease)]
    conflicts = [result for result in results if isinstance(result, LeaseConflictError)]
    assert len(leases) == 1
    assert len(conflicts) == 1
    assert store.get(session_id) == leases[0]


def test_release_reacquire_increments_token_and_rejects_stale_fence(tmp_path: Path) -> None:
    clock = ManualClock(NOW)
    store = SQLiteLeaseStore(tmp_path / "leases.db", clock=clock)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
        checkpoint=4,
    )
    store.release(session_id, fence=first.fence)
    assert store.get(session_id) is None

    clock.advance(seconds=1)
    second = store.acquire(
        session_id,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
    )
    assert second.fence.control_plane_epoch == first.fence.control_plane_epoch
    assert second.fence.fencing_token == first.fence.fencing_token + 1
    assert second.checkpoint == first.checkpoint

    with pytest.raises(LeaseLostError):
        store.heartbeat(
            session_id,
            fence=first.fence,
            ttl=timedelta(seconds=30),
            checkpoint=4,
        )
    with pytest.raises(LeaseLostError):
        store.release(session_id, fence=first.fence)
    assert store.get(session_id) == second


def test_expiry_takeover_increments_token_at_database_clock_boundary(tmp_path: Path) -> None:
    clock = ManualClock(NOW)
    store = SQLiteLeaseStore(tmp_path / "leases.db", clock=clock)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=10),
        checkpoint=2,
    )
    clock.advance(seconds=10)
    assert store.get(session_id) is None

    second = store.acquire(
        session_id,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
        checkpoint=3,
    )

    assert second.fence.fencing_token == first.fence.fencing_token + 1
    assert second.owner_instance_id == "worker-b"
    with pytest.raises(LeaseLostError):
        store.release(session_id, fence=first.fence)


def test_heartbeat_preserves_fence_and_rejects_checkpoint_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = ManualClock(NOW)
    store = SQLiteLeaseStore(tmp_path / "leases.db", clock=clock)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
        checkpoint=3,
    )
    clock.advance(seconds=5)
    original_get = store.get
    monkeypatch.setattr(
        store,
        "get",
        lambda _session_id: pytest.fail("heartbeat must not pre-read with get()"),
    )
    heartbeat = store.heartbeat(
        session_id,
        fence=first.fence,
        ttl=timedelta(seconds=30),
        checkpoint=9,
    )

    assert heartbeat.fence == first.fence
    assert heartbeat.acquired_at == first.acquired_at
    assert heartbeat.checkpoint == 9

    with pytest.raises(LeaseCheckpointRegressionError):
        store.heartbeat(
            session_id,
            fence=first.fence,
            ttl=timedelta(seconds=30),
            checkpoint=8,
        )
    assert original_get(session_id) == heartbeat


@pytest.mark.parametrize("changed", ["epoch", "token", "owner"])
def test_full_fence_cas_rejects_each_stale_component(
    tmp_path: Path,
    changed: str,
) -> None:
    store = SQLiteLeaseStore(tmp_path / "leases.db", clock=ManualClock(NOW))
    session_id = new_session_id()
    lease = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
    )
    values = lease.fence.model_dump()
    if changed == "epoch":
        values["control_plane_epoch"] = uuid4()
    elif changed == "token":
        values["fencing_token"] += 1
    else:
        values["owner_instance_id"] = "worker-b"
    stale = LeaseFence.model_validate(values)

    with pytest.raises(LeaseLostError):
        store.heartbeat(
            session_id,
            fence=stale,
            ttl=timedelta(seconds=30),
            checkpoint=0,
        )
    with pytest.raises(LeaseLostError):
        store.release(session_id, fence=stale)
    assert store.get(session_id) == lease


def test_epoch_mismatch_allows_immediate_takeover(tmp_path: Path) -> None:
    database_path = tmp_path / "leases.db"
    clock = ManualClock(NOW)
    store = SQLiteLeaseStore(database_path, clock=clock)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(hours=1),
    )
    next_epoch = uuid4()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE control_plane_epochs SET epoch = ? WHERE deployment_namespace = 'local'",
            (str(next_epoch),),
        )

    assert store.get(session_id) is None

    with pytest.raises(LeaseLostError):
        store.heartbeat(
            session_id,
            fence=first.fence,
            ttl=timedelta(seconds=30),
            checkpoint=0,
        )
    with pytest.raises(LeaseLostError):
        store.release(session_id, fence=first.fence)

    second = store.acquire(
        session_id,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
    )

    assert second.fence.control_plane_epoch == next_epoch
    assert second.fence.fencing_token == first.fence.fencing_token + 1
    with pytest.raises(LeaseLostError):
        store.release(session_id, fence=first.fence)


def test_legacy_row_fails_closed_without_promoting_checkpoint_to_token(tmp_path: Path) -> None:
    database_path = tmp_path / "leases.db"
    session_id = new_session_id()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE worker_leases (
                session_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL,
                checkpoint INTEGER NOT NULL, acquired_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO worker_leases VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(session_id),
                "legacy-worker",
                37,
                NOW.isoformat(),
                NOW.isoformat(),
                (NOW + timedelta(hours=1)).isoformat(),
            ),
        )

    store = SQLiteLeaseStore(database_path, clock=ManualClock(NOW))
    assert store.get(session_id) is None
    migrated = store.acquire(
        session_id,
        owner_instance_id="worker-new",
        ttl=timedelta(seconds=30),
    )

    assert migrated.fence.fencing_token == 1
    assert migrated.checkpoint == 37


def test_partial_fence_migration_fails_closed_idempotently(tmp_path: Path) -> None:
    database_path = tmp_path / "leases.db"
    session_id = new_session_id()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE worker_leases (
                session_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL,
                checkpoint INTEGER NOT NULL, acquired_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                control_plane_epoch TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO worker_leases VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(session_id),
                "legacy-worker",
                41,
                NOW.isoformat(),
                NOW.isoformat(),
                (NOW + timedelta(hours=1)).isoformat(),
                None,
            ),
        )

    first = SQLiteLeaseStore(database_path, clock=ManualClock(NOW))
    second = SQLiteLeaseStore(database_path, clock=ManualClock(NOW))

    assert first.get(session_id) is None
    migrated = second.acquire(
        session_id,
        owner_instance_id="worker-new",
        ttl=timedelta(seconds=30),
    )
    assert migrated.checkpoint == 41
    assert migrated.fence.fencing_token == 1


def test_sqlite_lease_store_rejects_ttl_above_configured_maximum(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(
        tmp_path / "leases.db",
        clock=ManualClock(NOW),
        maximum_ttl=timedelta(seconds=30),
    )

    with pytest.raises(ValueError, match="configured maximum"):
        store.acquire(
            new_session_id(),
            owner_instance_id="worker-a",
            ttl=timedelta(seconds=31),
        )
