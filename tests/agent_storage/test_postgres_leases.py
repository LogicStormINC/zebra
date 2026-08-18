from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Thread
from time import monotonic, sleep
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.domain.leases import (
    LeaseCheckpointRegressionError,
    LeaseConflictError,
    LeaseFence,
    LeaseLostError,
    WorkerLease,
)
from agent_storage import (
    PostgresLeaseStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    rotate_control_plane_epoch,
)
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def lease_namespace(postgres_dsn: str) -> Generator[str]:
    namespace = f"lease-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_postgres_lease_acquires_typed_fence_and_uses_database_time(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    store = _store(postgres_dsn, lease_namespace)
    session_id = new_session_id()
    with psycopg.connect(postgres_dsn) as connection:
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]

    lease = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
        checkpoint=3,
    )

    with psycopg.connect(postgres_dsn) as connection:
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    assert before <= lease.acquired_at <= after
    assert lease.expires_at - lease.acquired_at == timedelta(seconds=30)
    assert lease.fence.fencing_token == 1
    assert lease.checkpoint == 3
    assert store.get(session_id) == lease


@pytest.mark.parametrize("second_owner", ["worker-a", "worker-b"])
def test_postgres_lease_rejects_active_reacquire(
    postgres_dsn: str,
    lease_namespace: str,
    second_owner: str,
) -> None:
    store = _store(postgres_dsn, lease_namespace)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
        checkpoint=4,
    )

    with pytest.raises(LeaseConflictError, match="active lease"):
        store.acquire(
            session_id,
            owner_instance_id=second_owner,
            ttl=timedelta(seconds=30),
            checkpoint=3,
        )
    assert store.get(session_id) == first


@pytest.mark.parametrize("owners", [("worker-a", "worker-b"), ("worker-a", "worker-a")])
def test_postgres_lease_allows_only_one_concurrent_acquirer(
    postgres_dsn: str,
    lease_namespace: str,
    owners: tuple[str, str],
) -> None:
    session_id = new_session_id()
    barrier = Barrier(2)

    def acquire(owner: str) -> WorkerLease | LeaseConflictError:
        barrier.wait()
        try:
            return _store(postgres_dsn, lease_namespace).acquire(
                session_id,
                owner_instance_id=owner,
                ttl=timedelta(seconds=30),
            )
        except LeaseConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(acquire, owners))

    assert sum(isinstance(result, WorkerLease) for result in results) == 1
    assert sum(isinstance(result, LeaseConflictError) for result in results) == 1


def test_heartbeat_preserves_fence_and_acquired_time_and_advances_checkpoint(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    store = _store(postgres_dsn, lease_namespace)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
        checkpoint=2,
    )
    heartbeat = store.heartbeat(
        session_id,
        fence=first.fence,
        ttl=timedelta(seconds=45),
        checkpoint=5,
    )

    assert heartbeat.fence == first.fence
    assert heartbeat.acquired_at == first.acquired_at
    assert heartbeat.heartbeat_at >= first.heartbeat_at
    assert heartbeat.expires_at > first.expires_at
    assert heartbeat.checkpoint == 5

    with pytest.raises(LeaseCheckpointRegressionError):
        store.heartbeat(
            session_id,
            fence=first.fence,
            ttl=timedelta(seconds=30),
            checkpoint=4,
        )


def test_release_retains_generation_and_reacquire_increments_token(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    store = _store(postgres_dsn, lease_namespace)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
        checkpoint=7,
    )
    store.release(session_id, fence=first.fence)

    assert store.get(session_id) is None
    with psycopg.connect(postgres_dsn) as connection:
        retained = connection.execute(
            """
            SELECT fencing_token, checkpoint, released_at IS NOT NULL
            FROM worker_leases WHERE deployment_namespace = %s AND session_id = %s
            """,
            (lease_namespace, session_id),
        ).fetchone()
    assert retained == (1, 7, True)
    with pytest.raises(LeaseLostError):
        store.heartbeat(
            session_id,
            fence=first.fence,
            ttl=timedelta(seconds=30),
            checkpoint=7,
        )
    with pytest.raises(LeaseCheckpointRegressionError):
        store.acquire(
            session_id,
            owner_instance_id="worker-b",
            ttl=timedelta(seconds=30),
            checkpoint=6,
        )

    second = store.acquire(
        session_id,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
    )
    assert second.fence.fencing_token == 2
    assert second.checkpoint == 7
    with pytest.raises(LeaseLostError):
        store.release(session_id, fence=first.fence)


def test_database_expiry_takeover_increments_token(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    store = _store(postgres_dsn, lease_namespace)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
    )
    _expire(postgres_dsn, lease_namespace, session_id)

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
    assert second.fence.fencing_token == 2


def test_restore_rotation_waits_for_inflight_fenced_mutation(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    session_id = new_session_id()
    initial = _store(postgres_dsn, lease_namespace).acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(minutes=5),
    )
    heartbeat_app = f"lease-heartbeat-{uuid4()}"
    rotation_app = f"epoch-rotation-{uuid4()}"
    heartbeat_dsn = make_conninfo(postgres_dsn, application_name=heartbeat_app)
    rotation_dsn = make_conninfo(postgres_dsn, application_name=rotation_app)
    heartbeats: list[WorkerLease] = []
    rotations: list[UUID] = []
    errors: list[BaseException] = []
    blocker = psycopg.connect(postgres_dsn)
    blocker.execute(
        """
        SELECT session_id FROM worker_leases
        WHERE deployment_namespace = %s AND session_id = %s
        FOR UPDATE
        """,
        (lease_namespace, session_id),
    ).fetchone()

    def heartbeat() -> None:
        try:
            heartbeats.append(
                _store(heartbeat_dsn, lease_namespace).heartbeat(
                    session_id,
                    fence=initial.fence,
                    ttl=timedelta(seconds=30),
                    checkpoint=1,
                )
            )
        except BaseException as error:
            errors.append(error)

    def rotate() -> None:
        try:
            rotations.append(
                rotate_control_plane_epoch(
                    rotation_dsn,
                    deployment_namespace=lease_namespace,
                )
            )
        except BaseException as error:
            errors.append(error)

    heartbeat_thread = Thread(target=heartbeat)
    rotation_thread = Thread(target=rotate)
    try:
        heartbeat_thread.start()
        _wait_for_database_lock(postgres_dsn, heartbeat_app)
        rotation_thread.start()
        _wait_for_database_lock(postgres_dsn, rotation_app)
        assert rotation_thread.is_alive()
        blocker.commit()
    finally:
        blocker.close()
    heartbeat_thread.join(timeout=3)
    rotation_thread.join(timeout=3)

    assert not heartbeat_thread.is_alive()
    assert not rotation_thread.is_alive()
    assert errors == []
    assert heartbeats[0].checkpoint == 1
    assert rotations[0] != initial.fence.control_plane_epoch
    with pytest.raises(LeaseLostError):
        _store(postgres_dsn, lease_namespace).heartbeat(
            session_id,
            fence=initial.fence,
            ttl=timedelta(seconds=30),
            checkpoint=2,
        )


@pytest.mark.parametrize("changed", ["epoch", "token", "owner"])
def test_full_fence_cas_rejects_each_stale_component(
    postgres_dsn: str,
    lease_namespace: str,
    changed: str,
) -> None:
    store = _store(postgres_dsn, lease_namespace)
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


def test_restore_rotation_invalidates_old_fence_without_waiting_for_ttl(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    store = _store(postgres_dsn, lease_namespace)
    session_id = new_session_id()
    first = store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(hours=1),
    )
    next_epoch = rotate_control_plane_epoch(
        postgres_dsn,
        deployment_namespace=lease_namespace,
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
    assert second.fence.fencing_token == 2


def test_namespace_fence_cannot_authorize_same_session_in_another_namespace(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    other_namespace = f"lease-other-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=other_namespace)
    session_id = new_session_id()
    first_store = _store(postgres_dsn, lease_namespace)
    second_store = _store(postgres_dsn, other_namespace)
    first = first_store.acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
    )
    second = second_store.acquire(
        session_id,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
    )

    try:
        assert first.fence.fencing_token == second.fence.fencing_token == 1
        with pytest.raises(LeaseLostError):
            second_store.heartbeat(
                session_id,
                fence=first.fence,
                ttl=timedelta(seconds=30),
                checkpoint=0,
            )
    finally:
        _delete_namespace(postgres_dsn, other_namespace)


def test_database_time_is_independent_of_session_timezone(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    ahead_dsn = make_conninfo(postgres_dsn, options="-c timezone=Pacific/Kiritimati")
    behind_dsn = make_conninfo(postgres_dsn, options="-c timezone=Pacific/Honolulu")
    session_id = new_session_id()
    first = _store(ahead_dsn, lease_namespace).acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(seconds=30),
    )

    with pytest.raises(LeaseConflictError):
        _store(behind_dsn, lease_namespace).acquire(
            session_id,
            owner_instance_id="worker-b",
            ttl=timedelta(seconds=30),
        )
    _expire(postgres_dsn, lease_namespace, session_id)
    second = _store(behind_dsn, lease_namespace).acquire(
        session_id,
        owner_instance_id="worker-b",
        ttl=timedelta(seconds=30),
    )
    assert second.fence.fencing_token == first.fence.fencing_token + 1


def test_postgres_lease_validates_ttl_checkpoint_and_owner(
    postgres_dsn: str,
    lease_namespace: str,
) -> None:
    store = PostgresLeaseStore(
        postgres_dsn,
        deployment_namespace=lease_namespace,
        maximum_ttl=timedelta(seconds=30),
    )
    session_id = new_session_id()

    for invalid_ttl in (timedelta(0), timedelta(seconds=31)):
        with pytest.raises(ValueError, match="lease ttl"):
            store.acquire(
                session_id,
                owner_instance_id="worker-a",
                ttl=invalid_ttl,
            )
    with pytest.raises(ValueError, match="checkpoint"):
        store.acquire(
            session_id,
            owner_instance_id="worker-a",
            ttl=timedelta(seconds=30),
            checkpoint=-1,
        )
    with pytest.raises(ValueError, match="owner_instance_id"):
        store.acquire(
            session_id,
            owner_instance_id=" ",
            ttl=timedelta(seconds=30),
        )


def _store(dsn: str, namespace: str) -> PostgresLeaseStore:
    return PostgresLeaseStore(dsn, deployment_namespace=namespace)


def _expire(dsn: str, namespace: str, session_id: SessionId) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            UPDATE worker_leases
            SET acquired_at = transaction_timestamp() - interval '3 seconds',
                heartbeat_at = transaction_timestamp() - interval '2 seconds',
                expires_at = transaction_timestamp() - interval '1 second'
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (namespace, session_id),
        )


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "DELETE FROM worker_leases WHERE deployment_namespace = %s",
            (namespace,),
        )
        connection.execute(
            "DELETE FROM control_plane_epochs WHERE deployment_namespace = %s",
            (namespace,),
        )


def _wait_for_database_lock(dsn: str, application_name: str) -> None:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        with psycopg.connect(dsn) as connection:
            row = connection.execute(
                """
                SELECT wait_event_type FROM pg_stat_activity
                WHERE application_name = %s
                """,
                (application_name,),
            ).fetchone()
        if row == ("Lock",):
            return
        sleep(0.01)
    raise AssertionError(f"{application_name} did not block on the expected database lock")
