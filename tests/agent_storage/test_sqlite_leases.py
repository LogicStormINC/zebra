from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_session_id
from agent_storage import LeaseConflictError, SQLiteLeaseStore


def test_sqlite_lease_store_acquires_and_reads_active_lease(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(tmp_path / "leases.db")
    session_id = new_session_id()
    acquired_at = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)

    lease = store.acquire(
        session_id,
        worker_id="worker-a",
        acquired_at=acquired_at,
        expires_at=acquired_at + timedelta(seconds=30),
        checkpoint=3,
    )

    assert lease.worker_id == "worker-a"
    assert lease.checkpoint == 3
    assert store.get(session_id) == lease


def test_sqlite_lease_store_rejects_other_worker_before_expiry(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(tmp_path / "leases.db")
    session_id = new_session_id()
    acquired_at = datetime(2026, 6, 21, 10, 5, tzinfo=UTC)
    store.acquire(
        session_id,
        worker_id="worker-a",
        acquired_at=acquired_at,
        expires_at=acquired_at + timedelta(seconds=30),
    )

    with pytest.raises(
        LeaseConflictError,
        match="session already leased by another worker",
    ):
        store.acquire(
            session_id,
            worker_id="worker-b",
            acquired_at=acquired_at + timedelta(seconds=5),
            expires_at=acquired_at + timedelta(seconds=35),
        )


def test_sqlite_lease_store_allows_reacquire_after_expiry(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(tmp_path / "leases.db")
    session_id = new_session_id()
    acquired_at = datetime(2026, 6, 21, 10, 10, tzinfo=UTC)
    store.acquire(
        session_id,
        worker_id="worker-a",
        acquired_at=acquired_at,
        expires_at=acquired_at + timedelta(seconds=10),
        checkpoint=2,
    )

    renewed = store.acquire(
        session_id,
        worker_id="worker-b",
        acquired_at=acquired_at + timedelta(seconds=11),
        expires_at=acquired_at + timedelta(seconds=41),
        checkpoint=4,
    )

    assert renewed.worker_id == "worker-b"
    assert renewed.checkpoint == 4
    assert store.get(session_id) == renewed


def test_sqlite_lease_store_heartbeats_owned_lease(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(tmp_path / "leases.db")
    session_id = new_session_id()
    acquired_at = datetime(2026, 6, 21, 10, 15, tzinfo=UTC)
    store.acquire(
        session_id,
        worker_id="worker-a",
        acquired_at=acquired_at,
        expires_at=acquired_at + timedelta(seconds=30),
        checkpoint=1,
    )

    heartbeat = store.heartbeat(
        session_id,
        worker_id="worker-a",
        heartbeat_at=acquired_at + timedelta(seconds=5),
        expires_at=acquired_at + timedelta(seconds=35),
        checkpoint=2,
    )

    assert heartbeat.checkpoint == 2
    assert heartbeat.heartbeat_at == acquired_at + timedelta(seconds=5)
    assert store.get(session_id) == heartbeat


def test_sqlite_lease_store_releases_owned_lease(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(tmp_path / "leases.db")
    session_id = new_session_id()
    acquired_at = datetime(2026, 6, 21, 10, 20, tzinfo=UTC)
    store.acquire(
        session_id,
        worker_id="worker-a",
        acquired_at=acquired_at,
        expires_at=acquired_at + timedelta(seconds=30),
    )

    store.release(session_id, worker_id="worker-a")

    assert store.get(session_id) is None
