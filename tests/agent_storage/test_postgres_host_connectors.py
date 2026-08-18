"""Real-PostgreSQL tests for the outbound Host connector registry (v24)."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from agent_core.domain.host_connectors import (
    HostConnectorBinding,
    HostConnectorProfileVersion,
    HostConnectorStatus,
)
from agent_storage import (
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
from psycopg import connect


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"connector-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


def _profile(host_app_id: str, revision: int = 1) -> HostConnectorProfileVersion:
    return HostConnectorProfileVersion(
        host_app_id=host_app_id,
        connector_id=f"{host_app_id}-main",
        profile_revision=revision,
        base_uri="https://host.example.com",
        manifest_path="/manifest",
        invoke_path_template="/tools/invoke",
        reconcile_path_template="/tools/reconcile",
        supported_protocol_versions=("host-capability-protocol/1",),
        workload_identity_ref="workload/zebra-worker",
        credential_ref="credentials/host-hmac",
    )


def _registry(dsn: str, deployment_namespace: str) -> PostgresHostConnectorRegistry:
    return PostgresHostConnectorRegistry(dsn, deployment_namespace=deployment_namespace)


def test_publish_is_idempotent_per_revision(namespace: str, postgres_dsn: str) -> None:
    registry = _registry(postgres_dsn, namespace)
    profile = _profile("host-a")
    assert registry.publish_profile(profile).profile_digest == profile.profile_digest
    again = registry.publish_profile(profile)
    assert again.profile_digest == profile.profile_digest
    stored = registry.get_profile("host-a", "host-a-main", 1)
    assert stored is not None
    assert stored.base_uri == "https://host.example.com"
    assert stored.status is HostConnectorStatus.PUBLISHED


def test_rebinding_a_revision_is_rejected_on_digest_change(
    namespace: str, postgres_dsn: str
) -> None:
    registry = _registry(postgres_dsn, namespace)
    registry.publish_profile(_profile("host-b"))
    with pytest.raises(ValueError, match="immutable"):
        registry.publish_profile(
            HostConnectorProfileVersion(
                host_app_id="host-b",
                connector_id="host-b-main",
                profile_revision=1,
                base_uri="https://other.example.com",
                manifest_path="/manifest",
                invoke_path_template="/tools/invoke",
                supported_protocol_versions=("host-capability-protocol/1",),
                workload_identity_ref="workload/zebra-worker",
                credential_ref="credentials/host-hmac",
            )
        )


def test_binding_pins_namespace_and_cas_advances(
    namespace: str, postgres_dsn: str
) -> None:
    registry = _registry(postgres_dsn, namespace)
    registry.publish_profile(_profile("host-c", revision=1))
    registry.publish_profile(_profile("host-c", revision=2))
    first = registry.bind(
        HostConnectorBinding(
            host_app_id="host-c",
            namespace_id="tenant-a",
            connector_id="host-c-main",
            profile_revision=1,
            binding_revision=1,
        )
    )
    assert first.binding_revision == 1
    second = registry.bind(
        HostConnectorBinding(
            host_app_id="host-c",
            namespace_id="tenant-a",
            connector_id="host-c-main",
            profile_revision=2,
            binding_revision=1,
        )
    )
    assert second.binding_revision == 2
    resolved = registry.resolve_binding("host-c", "tenant-a")
    assert resolved is not None
    assert resolved.profile_revision == 2
    assert registry.resolve_binding("host-c", "tenant-unknown") is None


def test_namespaces_are_isolated(namespace: str, postgres_dsn: str) -> None:
    other = f"connector-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=other)
    first = _registry(postgres_dsn, namespace)
    second = _registry(postgres_dsn, other)
    first.publish_profile(_profile("host-d"))
    assert second.get_profile("host-d", "host-d-main", 1) is None


def test_missing_profile_cannot_bind(namespace: str, postgres_dsn: str) -> None:
    registry = _registry(postgres_dsn, namespace)
    with pytest.raises(ValueError, match="missing profile"):
        registry.bind(
            HostConnectorBinding(
                host_app_id="host-e",
                namespace_id="tenant-a",
                connector_id="host-e-main",
                profile_revision=9,
                binding_revision=1,
            )
        )


def test_migration_v24_tables_exist(postgres_dsn: str, namespace: str) -> None:
    with connect(postgres_dsn) as connection:
        rows = connection.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_name IN
                ('host_connector_profiles', 'host_connector_bindings')
            """
        ).fetchall()
    assert {row[0] for row in rows} == {
        "host_connector_profiles",
        "host_connector_bindings",
    }
