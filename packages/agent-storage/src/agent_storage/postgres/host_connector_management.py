"""Approved native connector publication/binding with atomic operation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from agent_core.domain.host_connectors import (
    HostConnectorBinding,
    HostConnectorProfileVersion,
    HostConnectorStatus,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.host_connectors import (
    PostgresHostConnectorRegistry,
    _binding_from_row,
)
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementStore,
    HostManagementTrust,
    HostManagementUnavailable,
    _canonical,
    _revision,
)

_BINDING_WHERE = "deployment_namespace=%s AND host_app_id=%s AND namespace_id=%s"


@dataclass(frozen=True)
class ManagedHostConnector:
    binding: HostConnectorBinding | None
    profile: HostConnectorProfileVersion | None
    approved_profile: HostConnectorProfileVersion
    revision: int
    replayed: bool = False


class HostConnectorManagementStore:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._management = HostManagementStore(dsn, deployment_namespace=deployment_namespace)
        self._registry = PostgresHostConnectorRegistry(
            dsn, deployment_namespace=deployment_namespace
        )

    @property
    def deployment_namespace(self) -> str:
        return self._management.deployment_namespace

    @staticmethod
    def _approved(trust: HostManagementTrust, profile: HostConnectorProfileVersion) -> None:
        if profile.host_app_id != trust.host_app_id:
            raise HostManagementUnavailable("Connector Host differs from approval")
        if profile.status is not HostConnectorStatus.PUBLISHED:
            raise HostManagementConflict("Approved connector profile must be published")

    def read(
        self, trust: HostManagementTrust, approved_profile: HostConnectorProfileVersion
    ) -> ManagedHostConnector:
        self._approved(trust, approved_profile)
        with self._management.authorized(trust) as connection:
            row = connection.execute(
                f"SELECT * FROM host_connector_bindings WHERE {_BINDING_WHERE} FOR SHARE",
                self._management._binding(trust),
            ).fetchone()
            result = self._snapshot(connection, row, approved_profile)
            self._management._live(connection, trust)
            return result

    def apply(
        self,
        trust: HostManagementTrust,
        approved_profile: HostConnectorProfileVersion,
        expected_revision: int,
        operation_id: str,
        active: bool,
    ) -> ManagedHostConnector:
        _revision(expected_revision, maximum=2**53 - 2)
        if not isinstance(operation_id, str) or str(UUID(operation_id)) != operation_id:
            raise ValueError("operation_id must be a canonical UUID")
        if type(active) is not bool:
            raise ValueError("active must be boolean")
        self._approved(trust, approved_profile)
        digest = sha256(
            _canonical(
                {
                    "trust_revision": trust.revision,
                    "fingerprint": trust.fingerprint,
                    "expected_revision": expected_revision,
                    "active": active,
                    "approved_profile": approved_profile.model_dump(mode="json"),
                }
            ).encode()
        ).hexdigest()
        with self._management.authorized(trust) as connection:
            key = self._management._binding(trust)
            receipt = connection.execute(
                f"SELECT * FROM host_connector_management_receipts WHERE {_BINDING_WHERE} "
                "AND operation_id=%s",
                (*key, operation_id),
            ).fetchone()
            if receipt is not None:
                if receipt["payload_digest"] != digest:
                    raise HostManagementConflict("Operation was used with a different payload")
                self._management._live(connection, trust)
                saved = receipt["snapshot"]
                return ManagedHostConnector(
                    HostConnectorBinding.model_validate(saved["binding"]),
                    HostConnectorProfileVersion.model_validate(saved["profile"]),
                    HostConnectorProfileVersion.model_validate(saved["approved_profile"]),
                    int(receipt["revision"]),
                    True,
                )
            if active:
                try:
                    self._registry._publish_profile(connection, approved_profile)
                except ValueError as error:
                    raise HostManagementConflict("Connector publication conflicts") from error
                self._management._live(connection, trust)
            current = connection.execute(
                f"SELECT * FROM host_connector_bindings WHERE {_BINDING_WHERE} FOR UPDATE", key
            ).fetchone()
            self._management._live(connection, trust)
            if (0 if current is None else current["binding_revision"]) != expected_revision:
                raise HostManagementConflict("Connector binding revision changed")
            if current is None:
                if not active:
                    raise HostManagementConflict("Cannot disable a missing connector binding")
                changed = connection.execute(
                    """INSERT INTO host_connector_bindings (
                        deployment_namespace,host_app_id,namespace_id,connector_id,
                        profile_revision,binding_revision,active
                    ) VALUES (%s,%s,%s,%s,%s,1,TRUE)
                    ON CONFLICT (deployment_namespace,host_app_id,namespace_id) DO NOTHING
                    RETURNING *""",
                    (*key, approved_profile.connector_id, approved_profile.profile_revision),
                ).fetchone()
            else:
                connector = approved_profile.connector_id if active else current["connector_id"]
                revision = (
                    approved_profile.profile_revision if active else current["profile_revision"]
                )
                changed = connection.execute(
                    f"""UPDATE host_connector_bindings SET connector_id=%s,profile_revision=%s,
                        active=%s,binding_revision=binding_revision+1,updated_at=clock_timestamp()
                    WHERE {_BINDING_WHERE} AND binding_revision=%s RETURNING *""",
                    (connector, revision, active, *key, expected_revision),
                ).fetchone()
            if changed is None:
                raise HostManagementConflict("Connector binding changed during creation")
            result = self._snapshot(connection, changed, approved_profile)
            connection.execute(
                """INSERT INTO host_connector_management_receipts (
                    deployment_namespace,host_app_id,namespace_id,operation_id,
                    payload_digest,snapshot,revision
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (*key, operation_id, digest, Jsonb(_saved(result)), result.revision),
            )
            self._audit(connection, trust, result.revision, operation_id, active)
            self._management._live(connection, trust)
            return result

    def _snapshot(
        self,
        connection: Any,
        row: dict[str, Any] | None,
        approved: HostConnectorProfileVersion,
    ) -> ManagedHostConnector:
        if row is None:
            return ManagedHostConnector(None, None, approved, 0)
        binding = _binding_from_row(row)
        profile = self._registry._get_profile(
            connection, binding.host_app_id, binding.connector_id, binding.profile_revision
        )
        if profile is None:
            raise HostManagementUnavailable("Current connector profile is unavailable")
        return ManagedHostConnector(binding, profile, approved, binding.binding_revision)

    def _audit(
        self,
        connection: Any,
        trust: HostManagementTrust,
        revision: int,
        operation_id: str,
        active: bool,
    ) -> None:
        connection.execute(
            """INSERT INTO host_connector_management_audit (
                deployment_namespace,host_app_id,namespace_id,trust_revision,fingerprint,
                binding_revision,operation_id,active
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                *self._management._binding(trust),
                trust.revision,
                trust.fingerprint,
                revision,
                operation_id,
                active,
            ),
        )


def _saved(result: ManagedHostConnector) -> dict[str, Any]:
    return {
        "binding": None if result.binding is None else result.binding.model_dump(mode="json"),
        "profile": None if result.profile is None else result.profile.model_dump(mode="json"),
        "approved_profile": result.approved_profile.model_dump(mode="json"),
    }
