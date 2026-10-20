"""Host-scoped freezes share digests without dropping immutable revision identity."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from agent_core.domain.host_connectors import HostConnectorProfileVersion
from agent_integrations.host_tools import HostToolManifest
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
from agent_storage.postgres.host_manifest_freeze import (
    load_frozen_manifest,
    load_frozen_manifest_by_digest,
    store_frozen_manifest,
)


def payload(description="first"):
    return HostToolManifest.from_payload(
        {"workloadIdentity": "worker", "tools": [
            {"name": "records.read", "description": description,
             "scopes": ["record.read"], "resourceBindings": []},
        ]}, binding_policy="declared",
    ).to_payload()


def publish(dsn, namespace, host):
    PostgresHostConnectorRegistry(dsn, deployment_namespace=namespace).publish_profile(
        HostConnectorProfileVersion(
            host_app_id=host, connector_id="main", profile_revision=1,
            base_uri="https://host.example", manifest_path="/manifest",
            invoke_path_template="/execute", supported_protocol_versions=("v1",),
            workload_identity_ref="worker", credential_ref="credentials/host",
        )
    )


def store(dsn, namespace, value, *, host="catalog", connector="main", revision=1):
    store_frozen_manifest(
        dsn, deployment_namespace=namespace, host_app_id=host, connector_id=connector,
        profile_revision=revision, manifest_digest=value["manifestDigest"],
        manifest_payload=value,
    )


def load(dsn, namespace, *, host="catalog", connector="main", revision=1):
    return load_frozen_manifest(
        dsn, deployment_namespace=namespace, host_app_id=host, connector_id=connector,
        profile_revision=revision,
    )


def test_shared_digest_has_every_revision_and_connector_association(postgres_dsn):
    namespace = f"freeze-shared-{uuid4()}"
    value = payload()
    for connector, revision in [("main", 1), ("main", 2), ("other", 1)]:
        store(postgres_dsn, namespace, value, connector=connector, revision=revision)
        assert load(postgres_dsn, namespace, connector=connector, revision=revision) == value
    with pytest.raises(ValueError, match="conflict"):
        store(postgres_dsn, namespace, payload("changed"), revision=2)
    assert load(postgres_dsn, namespace, revision=2) == value
    assert load_frozen_manifest_by_digest(
        postgres_dsn, deployment_namespace=namespace, manifest_digest=value["manifestDigest"],
    ) == value


def test_same_connector_and_revision_are_isolated_by_host(postgres_dsn):
    namespace = f"freeze-host-{uuid4()}"
    for host in ("catalog", "archive"):
        value = payload(host)
        store(postgres_dsn, namespace, value, host=host)
        assert load(postgres_dsn, namespace, host=host) == value
    assert load(postgres_dsn, namespace, host="catalog") == payload("catalog")
    with pytest.raises(ValueError, match="explicit Host"):
        load(postgres_dsn, namespace, host=None)


def test_legacy_rows_remain_unchanged_and_require_unambiguous_host(postgres_dsn):
    namespace = f"freeze-legacy-{uuid4()}"
    value = payload()
    store(postgres_dsn, namespace, value, host=None)
    database = PostgresDatabase(postgres_dsn, deployment_namespace=namespace)
    with database.connect() as connection:
        before = connection.execute(
            "SELECT * FROM host_manifest_freezes WHERE deployment_namespace=%s", (namespace,),
        ).fetchall()
    with pytest.raises(ValueError, match="ownership is ambiguous"):
        load(postgres_dsn, namespace)
    publish(postgres_dsn, namespace, "catalog")
    assert load(postgres_dsn, namespace) == value
    store(postgres_dsn, namespace, value)
    assert load_frozen_manifest_by_digest(
        postgres_dsn, deployment_namespace=namespace, manifest_digest=value["manifestDigest"],
    ) == value
    publish(postgres_dsn, namespace, "archive")
    assert load(postgres_dsn, namespace, host="catalog") == value
    with pytest.raises(ValueError, match="ownership is ambiguous"):
        load(postgres_dsn, namespace, host="archive")
    with database.connect() as connection:
        after = connection.execute(
            "SELECT * FROM host_manifest_freezes WHERE deployment_namespace=%s", (namespace,),
        ).fetchall()
    assert before == after


def test_legacy_helper_never_succeeds_without_persisting_revision(postgres_dsn):
    namespace = f"freeze-legacy-conflict-{uuid4()}"
    value = payload()
    store(postgres_dsn, namespace, value, host=None)
    with pytest.raises(ValueError, match="conflict"):
        store(postgres_dsn, namespace, value, host=None, revision=2)
    assert load(postgres_dsn, namespace, host=None, revision=2) is None


@pytest.mark.parametrize("same_digest", [False, True])
def test_concurrent_freezes_preserve_one_revision(postgres_dsn, same_digest):
    namespace = f"freeze-race-{uuid4()}"
    barrier = Barrier(2)

    def attempt(value):
        barrier.wait(timeout=10)
        try:
            store(postgres_dsn, namespace, value)
        except ValueError:
            return None
        return value

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = (payload("one"), payload("one" if same_digest else "two"))
        results = list(pool.map(attempt, values))
    winners = [result for result in results if result is not None]
    assert len(winners) == (2 if same_digest else 1)
    assert load(postgres_dsn, namespace) == winners[0]


@pytest.mark.parametrize("first_host", [None, "catalog"])
@pytest.mark.parametrize("same_digest", [False, True])
def test_mixed_writer_generations_share_one_immutable_revision(
    postgres_dsn, first_host, same_digest,
):
    namespace = f"freeze-mixed-{uuid4()}"
    publish(postgres_dsn, namespace, "catalog")
    first = payload("one")
    second = first if same_digest else payload("two")
    store(postgres_dsn, namespace, first, host=first_host)
    second_host = "catalog" if first_host is None else None
    if same_digest:
        store(postgres_dsn, namespace, second, host=second_host)
    else:
        with pytest.raises(ValueError, match="digest changed|conflict"):
            store(postgres_dsn, namespace, second, host=second_host)
    assert load(postgres_dsn, namespace, host=None) == first
    assert load(postgres_dsn, namespace, host="catalog") == first


@pytest.mark.parametrize("same_digest", [False, True])
def test_concurrent_mixed_writers_never_report_divergent_success(postgres_dsn, same_digest):
    namespace = f"freeze-mixed-race-{uuid4()}"
    publish(postgres_dsn, namespace, "catalog")
    barrier = Barrier(2)
    first = payload("one")
    second = first if same_digest else payload("two")

    def attempt(item):
        host, value = item
        barrier.wait(timeout=10)
        try:
            store(postgres_dsn, namespace, value, host=host)
        except ValueError:
            return None
        return value

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ((None, first), ("catalog", second))))
    winners = [result for result in results if result is not None]
    assert len(winners) == (2 if same_digest else 1)
    assert all(result == winners[0] for result in winners)
    assert load(postgres_dsn, namespace, host=None) == winners[0]
    assert load(postgres_dsn, namespace, host="catalog") == winners[0]


def test_hostless_write_cannot_choose_between_multiple_scoped_hosts(postgres_dsn):
    namespace = f"freeze-ambiguous-write-{uuid4()}"
    value = payload()
    for host in ("catalog", "archive"):
        store(postgres_dsn, namespace, value, host=host)
    with pytest.raises(ValueError, match="explicit Host"):
        store(postgres_dsn, namespace, value, host=None)
