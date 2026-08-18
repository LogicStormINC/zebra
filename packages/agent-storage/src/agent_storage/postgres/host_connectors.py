"""PostgreSQL implementation of the outbound Host connector registry.

AL-CONNECTOR-PG-01: profiles are immutable per revision (publish inserts a
new row, never updates), namespace bindings move via compare-and-swap on
``binding_revision``, and every write is namespace-isolated under the
deployment namespace.
"""

from __future__ import annotations

from agent_core.domain.host_connectors import (
    HostConnectorBinding,
    HostConnectorProfileVersion,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase

_INSERT_PROFILE = """
    INSERT INTO host_connector_profiles (
        deployment_namespace, host_app_id, connector_id, profile_revision,
        base_uri, manifest_path, invoke_path_template, reconcile_path_template,
        supported_protocol_versions, workload_identity_ref, credential_ref,
        network_policy_ref, status, profile_digest
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (deployment_namespace, host_app_id, connector_id, profile_revision)
    DO NOTHING
    RETURNING host_app_id, connector_id, profile_revision
"""

_SELECT_PROFILE = """
    SELECT base_uri, manifest_path, invoke_path_template, reconcile_path_template,
        supported_protocol_versions, workload_identity_ref, credential_ref,
        network_policy_ref, status
    FROM host_connector_profiles
    WHERE deployment_namespace = %s AND host_app_id = %s AND connector_id = %s
        AND profile_revision = %s
"""

_UPSERT_BINDING = """
    INSERT INTO host_connector_bindings (
        deployment_namespace, host_app_id, namespace_id, connector_id,
        profile_revision, binding_revision, active
    ) VALUES (%s, %s, %s, %s, %s, 1, TRUE)
    ON CONFLICT (deployment_namespace, host_app_id, namespace_id)
    DO UPDATE SET connector_id = EXCLUDED.connector_id,
        profile_revision = EXCLUDED.profile_revision,
        binding_revision = host_connector_bindings.binding_revision + 1,
        active = TRUE,
        updated_at = transaction_timestamp()
    WHERE host_connector_bindings.active
    RETURNING host_app_id, namespace_id, connector_id, profile_revision,
        binding_revision, active
"""

_SELECT_BINDING = """
    SELECT host_app_id, namespace_id, connector_id, profile_revision,
        binding_revision, active
    FROM host_connector_bindings
    WHERE deployment_namespace = %s AND host_app_id = %s AND namespace_id = %s
        AND active
"""


class PostgresHostConnectorRegistry:
    """Namespace-isolated connector registry over the v24 schema."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def publish_profile(
        self,
        profile: HostConnectorProfileVersion,
    ) -> HostConnectorProfileVersion:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            row = connection.execute(
                _INSERT_PROFILE,
                (
                    namespace,
                    profile.host_app_id,
                    profile.connector_id,
                    profile.profile_revision,
                    profile.base_uri,
                    profile.manifest_path,
                    profile.invoke_path_template,
                    profile.reconcile_path_template,
                    Jsonb(list(profile.supported_protocol_versions)),
                    profile.workload_identity_ref,
                    profile.credential_ref,
                    profile.network_policy_ref,
                    profile.status.value,
                    profile.profile_digest,
                ),
            ).fetchone()
        if row is None:
            stored = self.get_profile(
                profile.host_app_id,
                profile.connector_id,
                profile.profile_revision,
            )
            if stored is None or stored.profile_digest != profile.profile_digest:
                raise ValueError(
                    "connector profile revision is immutable and already exists "
                    "with a different digest"
                )
            return profile
        return profile

    def get_profile(
        self,
        host_app_id: str,
        connector_id: str,
        profile_revision: int,
    ) -> HostConnectorProfileVersion | None:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            row = connection.execute(
                _SELECT_PROFILE,
                (namespace, host_app_id, connector_id, profile_revision),
            ).fetchone()
        if row is None:
            return None
        from agent_core.domain.host_connectors import HostConnectorStatus

        return HostConnectorProfileVersion(
            host_app_id=host_app_id,
            connector_id=connector_id,
            profile_revision=profile_revision,
            base_uri=row["base_uri"],
            manifest_path=row["manifest_path"],
            invoke_path_template=row["invoke_path_template"],
            reconcile_path_template=row["reconcile_path_template"],
            supported_protocol_versions=tuple(row["supported_protocol_versions"]),
            workload_identity_ref=row["workload_identity_ref"],
            credential_ref=row["credential_ref"],
            network_policy_ref=row["network_policy_ref"],
            status=HostConnectorStatus(row["status"]),
        )

    def resolve_binding(self, host_app_id: str, namespace_id: str) -> HostConnectorBinding | None:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            row = connection.execute(
                _SELECT_BINDING,
                (namespace, host_app_id, namespace_id),
            ).fetchone()
        if row is None:
            return None
        return HostConnectorBinding(
            host_app_id=row["host_app_id"],
            namespace_id=row["namespace_id"],
            connector_id=row["connector_id"],
            profile_revision=row["profile_revision"],
            binding_revision=row["binding_revision"],
            active=row["active"],
        )

    def bind(self, binding: HostConnectorBinding) -> HostConnectorBinding:
        namespace = self.deployment_namespace
        pinned = self.get_profile(
            binding.host_app_id,
            binding.connector_id,
            binding.profile_revision,
        )
        if pinned is None:
            raise ValueError("cannot bind a namespace to a missing profile revision")
        with self._database.connect() as connection:
            row = connection.execute(
                _UPSERT_BINDING,
                (
                    namespace,
                    binding.host_app_id,
                    binding.namespace_id,
                    binding.connector_id,
                    binding.profile_revision,
                ),
            ).fetchone()
        if row is None:
            raise ValueError("connector binding CAS failed")
        return HostConnectorBinding(
            host_app_id=row["host_app_id"],
            namespace_id=row["namespace_id"],
            connector_id=row["connector_id"],
            profile_revision=row["profile_revision"],
            binding_revision=row["binding_revision"],
            active=row["active"],
        )
