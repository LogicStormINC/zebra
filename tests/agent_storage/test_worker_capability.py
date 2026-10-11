"""Pure validation and real fixture-schema process leases; never business migrations."""

from uuid import uuid4

import pytest
from agent_storage import bootstrap_control_plane_epoch, rotate_control_plane_epoch
from agent_storage.postgres.worker_capability import (
    STRICT_WORKER_CONTRACT,
    PostgresWorkerCapabilities,
    WorkerCapabilityLostError,
    validate_capability_inputs,
)
from agent_storage.postgres.worker_capability_migration import WORKER_CAPABILITY_MIGRATION
from agent_storage.worker_capability_configuration import continuation_configuration_digest

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401

DIGEST = "a" * 64
NAMESPACE = "worker-capability-test"


def test_invalid_continuation_qualification_is_rejected_before_database():
    store = PostgresWorkerCapabilities("dbname=unused", deployment_namespace=NAMESPACE)
    with pytest.raises(ValueError, match="continuation qualification"):
        store.register(uuid4(), configuration_digest=DIGEST, continuation_digest="b" * 64)


def test_native_continuation_extension_is_process_bound_and_cannot_change(dsn):  # noqa: F811
    from agent_storage.postgres.worker_capability import pin_worker_capability

    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    store = PostgresWorkerCapabilities(dsn, deployment_namespace=NAMESPACE)
    qualification = continuation_configuration_digest(DIGEST)
    legacy = store.register(uuid4(), configuration_digest=DIGEST)
    qualified = store.register(
        uuid4(), configuration_digest=DIGEST, continuation_digest=qualification,
    )
    for lease, required in ((legacy, None), (qualified, None), (qualified, qualification)):
        with store._connect() as connection:
            pinned = pin_worker_capability(
                connection, NAMESPACE, contract=STRICT_WORKER_CONTRACT,
                configuration_digest=DIGEST, consumer_capability=lease,
                require_process=True, continuation_digest=required,
            )
            assert pinned.process_id == lease.process_id
    with store._connect() as connection, pytest.raises(WorkerCapabilityLostError):
        pin_worker_capability(
            connection, NAMESPACE, contract=STRICT_WORKER_CONTRACT,
            configuration_digest=DIGEST, consumer_capability=legacy,
            require_process=True, continuation_digest=qualification,
        )
    with pytest.raises(WorkerCapabilityLostError):
        store.heartbeat(legacy, configuration_digest=DIGEST, continuation_digest=qualification)
    with pytest.raises(WorkerCapabilityLostError):
        store.heartbeat(qualified, configuration_digest=DIGEST)
    renewed = store.heartbeat(
        qualified, configuration_digest=DIGEST, continuation_digest=qualification,
    )
    assert renewed.sequence == qualified.sequence + 1


@pytest.mark.parametrize("ttl", [True, False, 0, -1, 31, 1.0, "1"])
def test_invalid_ttl_is_rejected_without_database(ttl):
    with pytest.raises(ValueError):
        validate_capability_inputs(DIGEST, ttl)


@pytest.mark.parametrize("digest", [None, True, "", "A" * 64, "a" * 63, "g" * 64])
def test_configuration_digest_is_exact_canonical_sha256(digest):
    with pytest.raises(ValueError):
        validate_capability_inputs(digest, 30)


def test_contract_and_catalog_are_process_only_and_bounded():
    from agent_storage.postgres.migrations import MIGRATIONS

    assert "bounded-multipart:same-session:validation-mode:v3" in STRICT_WORKER_CONTRACT
    assert WORKER_CAPABILITY_MIGRATION in MIGRATIONS
    assert len({m.version for m in MIGRATIONS}) == len(MIGRATIONS)
    text = " ".join(WORKER_CAPABILITY_MIGRATION.statements)
    assert "runtime_instances" not in text and "worker_leases" not in text


def test_native_sequence_config_revoke_and_epoch(dsn):  # noqa: F811
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    store = PostgresWorkerCapabilities(dsn, deployment_namespace=NAMESPACE)
    first = store.register(uuid4(), configuration_digest=DIGEST)
    assert store.current(configuration_digest=DIGEST) == (first,)
    assert store.current(configuration_digest="b" * 64) == ()
    assert (
        PostgresWorkerCapabilities(dsn, deployment_namespace="other").current(
            configuration_digest=DIGEST
        )
        == ()
    )
    with pytest.raises(WorkerCapabilityLostError):
        store.heartbeat(first, configuration_digest="b" * 64)
    renewed = store.heartbeat(first, configuration_digest=DIGEST)
    assert renewed.process_id == first.process_id and renewed.sequence == first.sequence + 1
    with pytest.raises(WorkerCapabilityLostError):
        store.heartbeat(first, configuration_digest=DIGEST)
    store.revoke(first)  # Shutdown revocation is independent of the last heartbeat sequence.
    assert store.current(configuration_digest=DIGEST) == ()
    with pytest.raises(WorkerCapabilityLostError):
        store.heartbeat(renewed, configuration_digest=DIGEST)
    with pytest.raises(WorkerCapabilityLostError):
        store.register(first.process_id, configuration_digest=DIGEST)
    next_process = store.register(uuid4(), configuration_digest=DIGEST)
    rotate_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    assert store.current(configuration_digest=DIGEST) == ()
    with pytest.raises(WorkerCapabilityLostError):
        store.heartbeat(next_process, configuration_digest=DIGEST)


def test_native_expiry_never_resurrects_and_schema_is_bound(dsn):  # noqa: F811
    import psycopg

    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    store = PostgresWorkerCapabilities(dsn, deployment_namespace=NAMESPACE)
    lease = store.register(uuid4(), configuration_digest=DIGEST, ttl_seconds=1)
    with psycopg.connect(dsn) as connection:
        connection.execute("SELECT pg_sleep(1.05)")
    assert store.current(configuration_digest=DIGEST) == ()
    with pytest.raises(WorkerCapabilityLostError):
        store.heartbeat(lease, configuration_digest=DIGEST)
    with pytest.raises(WorkerCapabilityLostError):
        store.register(lease.process_id, configuration_digest=DIGEST)
    fresh = store.register(uuid4(), configuration_digest=DIGEST)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE worker_process_capabilities SET schema_oid=0 WHERE process_id=%s",
            (fresh.process_id,),
        )
    assert store.current(configuration_digest=DIGEST) == ()
    with pytest.raises(WorkerCapabilityLostError):
        store.heartbeat(fresh, configuration_digest=DIGEST)
