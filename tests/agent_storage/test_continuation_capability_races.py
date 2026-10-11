"""Native continuation capability lock ordering and transaction rollback."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from agent_storage import bootstrap_control_plane_epoch, rotate_control_plane_epoch
from agent_storage.postgres.worker_capability import (
    STRICT_WORKER_CONTRACT,
    PostgresWorkerCapabilities,
    WorkerCapabilityLostError,
    check_worker_capability_clock,
    pin_worker_capability,
)
from agent_storage.worker_capability_configuration import continuation_configuration_digest
from psycopg.conninfo import make_conninfo

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401

DIGEST = "a" * 64
NAMESPACE = "continuation-race-test"


def pin(connection, lease):
    return pin_worker_capability(
        connection, NAMESPACE, contract=STRICT_WORKER_CONTRACT,
        configuration_digest=DIGEST, consumer_capability=lease, require_process=True,
        continuation_digest=continuation_configuration_digest(DIGEST),
    )


@pytest.mark.parametrize("change", ["revoke", "epoch"])
def test_native_authority_change_serializes_with_qualified_pin(dsn, change):  # noqa: F811
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    store = PostgresWorkerCapabilities(dsn, deployment_namespace=NAMESPACE)
    lease = store.register(
        uuid4(), configuration_digest=DIGEST,
        continuation_digest=continuation_configuration_digest(DIGEST),
    )
    label = "qualification-race-" + uuid4().hex
    competing_dsn = make_conninfo(dsn, application_name=label)

    def mutate():
        if change == "revoke":
            PostgresWorkerCapabilities(
                competing_dsn, deployment_namespace=NAMESPACE,
            ).revoke(lease)
        else:
            rotate_control_plane_epoch(competing_dsn, deployment_namespace=NAMESPACE)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with store._connect() as connection:
            pinned = pin(connection, lease)
            blocker = connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            future = executor.submit(mutate)
            with psycopg.connect(dsn, autocommit=True) as observer:
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    blocked = observer.execute(
                        "SELECT 1 FROM pg_stat_activity WHERE application_name=%s "
                        "AND %s=ANY(pg_blocking_pids(pid))", (label, blocker),
                    ).fetchone()
                    if blocked:
                        break
                    observer.execute("SELECT pg_sleep(0.01)")
                assert blocked, "authority mutation must wait on the actual native pin lock"
            assert not future.done()
            check_worker_capability_clock(connection, pinned)
        future.result(timeout=5)
    with store._connect() as connection, pytest.raises(WorkerCapabilityLostError):
        pin(connection, lease)


def test_native_expiry_after_tentative_write_rolls_back(dsn):  # noqa: F811
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    store = PostgresWorkerCapabilities(dsn, deployment_namespace=NAMESPACE)
    lease = store.register(
        uuid4(), configuration_digest=DIGEST, ttl_seconds=1,
        continuation_digest=continuation_configuration_digest(DIGEST),
    )
    with store._connect() as connection:
        connection.execute("CREATE TEMP TABLE tentative_pickup (value INTEGER)")
        connection.commit()
        wrote = False
        with pytest.raises(WorkerCapabilityLostError), connection.transaction():
            pinned = pin(connection, lease)
            connection.execute("INSERT INTO tentative_pickup VALUES (1)")
            wrote = True
            connection.execute("SELECT pg_sleep(1.05)")
            check_worker_capability_clock(connection, pinned)
        assert wrote, "expiry must be detected after pin and the tentative write, not before"
        assert connection.execute("SELECT * FROM tentative_pickup").fetchall() == []
