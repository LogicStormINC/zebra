"""Immutable outbound Host profiles and namespace-isolated binding CAS."""

from __future__ import annotations

import json
from typing import Any

from agent_core.domain.host_connectors import HostConnectorBinding, HostConnectorProfileVersion
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.host_manifest_freeze import _legacy_revision

_PROFILE_WHERE = (
    "deployment_namespace=%s AND host_app_id=%s AND connector_id=%s AND profile_revision=%s"
)
_BINDING_WHERE = "deployment_namespace=%s AND host_app_id=%s AND namespace_id=%s"


class PostgresHostConnectorRegistry:
    """Namespace-isolated native registry; helpers also support atomic management writes."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def publish_profile(self, profile: HostConnectorProfileVersion) -> HostConnectorProfileVersion:
        with self._database.connect() as connection:
            return self._publish_profile(connection, profile)

    def _publish_profile(
        self, connection: Any, profile: HostConnectorProfileVersion
    ) -> HostConnectorProfileVersion:
        # Same key/order as both native freeze writers; no historical row is rewritten.
        lock_key = json.dumps(
            [
                "host-manifest-revision",
                self.deployment_namespace,
                profile.connector_id,
                profile.profile_revision,
            ]
        )
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
        _legacy_revision(
            connection,
            self.deployment_namespace,
            profile.connector_id,
            profile.profile_revision,
            profile.host_app_id,
        )
        key = (
            self.deployment_namespace,
            profile.host_app_id,
            profile.connector_id,
            profile.profile_revision,
        )
        row = connection.execute(
            f"SELECT * FROM host_connector_profiles WHERE {_PROFILE_WHERE} FOR UPDATE", key
        ).fetchone()
        if row is not None:
            if _profile_from_row(row) != profile or row["profile_digest"] != profile.profile_digest:
                raise ValueError("connector profile revision is immutable")
            return profile
        connection.execute(
            """INSERT INTO host_connector_profiles (
                deployment_namespace,host_app_id,connector_id,profile_revision,
                base_uri,manifest_path,invoke_path_template,reconcile_path_template,
                supported_protocol_versions,workload_identity_ref,credential_ref,
                network_policy_ref,status,profile_digest,manifest_binding_policy
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                *key,
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
                profile.manifest_binding_policy,
            ),
        )
        return profile

    def get_profile(
        self, host_app_id: str, connector_id: str, profile_revision: int
    ) -> HostConnectorProfileVersion | None:
        with self._database.connect() as connection:
            return self._get_profile(connection, host_app_id, connector_id, profile_revision)

    def _get_profile(
        self, connection: Any, host_app_id: str, connector_id: str, profile_revision: int
    ) -> HostConnectorProfileVersion | None:
        row = connection.execute(
            f"SELECT * FROM host_connector_profiles WHERE {_PROFILE_WHERE}",
            (self.deployment_namespace, host_app_id, connector_id, profile_revision),
        ).fetchone()
        return None if row is None else _profile_from_row(row)

    def resolve_binding(self, host_app_id: str, namespace_id: str) -> HostConnectorBinding | None:
        with self._database.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM host_connector_bindings WHERE {_BINDING_WHERE} AND active",
                (self.deployment_namespace, host_app_id, namespace_id),
            ).fetchone()
        return None if row is None else _binding_from_row(row)

    def bind(self, binding: HostConnectorBinding) -> HostConnectorBinding:
        with self._database.connect() as connection:
            pinned = self._get_profile(
                connection, binding.host_app_id, binding.connector_id, binding.profile_revision
            )
            if pinned is None:
                raise ValueError("cannot bind a namespace to a missing profile revision")
            key = self.deployment_namespace, binding.host_app_id, binding.namespace_id
            current = connection.execute(
                f"SELECT * FROM host_connector_bindings WHERE {_BINDING_WHERE} FOR UPDATE", key
            ).fetchone()
            if current is None:
                if binding.binding_revision != 1:
                    raise ValueError("connector binding creation requires revision 1")
                row = connection.execute(
                    """INSERT INTO host_connector_bindings (
                        deployment_namespace,host_app_id,namespace_id,connector_id,
                        profile_revision,binding_revision,active
                    ) VALUES (%s,%s,%s,%s,%s,1,TRUE)
                    ON CONFLICT (deployment_namespace,host_app_id,namespace_id) DO NOTHING
                    RETURNING *""",
                    (*key, binding.connector_id, binding.profile_revision),
                ).fetchone()
            else:
                row = connection.execute(
                    f"""UPDATE host_connector_bindings SET connector_id=%s,profile_revision=%s,
                        binding_revision=binding_revision+1,active=TRUE,
                        updated_at=transaction_timestamp()
                    WHERE {_BINDING_WHERE} AND active AND binding_revision=%s RETURNING *""",
                    (
                        binding.connector_id,
                        binding.profile_revision,
                        *key,
                        binding.binding_revision,
                    ),
                ).fetchone()
            if row is None:
                raise ValueError("connector binding CAS failed")
            return _binding_from_row(row)


def _profile_from_row(row: dict[str, Any]) -> HostConnectorProfileVersion:
    return HostConnectorProfileVersion.model_validate(
        {name: row[name] for name in HostConnectorProfileVersion.model_fields}
    )


def _binding_from_row(row: dict[str, Any]) -> HostConnectorBinding:
    return HostConnectorBinding.model_validate(
        {name: row[name] for name in HostConnectorBinding.model_fields}
    )
