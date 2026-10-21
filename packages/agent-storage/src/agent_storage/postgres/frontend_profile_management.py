"""Scoped intent over the existing native Profile aggregate, in one short transaction."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from agent_core.domain.client_capabilities import FrontendCapabilityProfileVersion, ProfileLifecycle
from psycopg.types.json import Jsonb

from agent_storage.postgres.client_capabilities import (
    PostgresClientCapabilityRegistry,
    lock_frontend_app,
)
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementStore,
    HostManagementTrust,
    HostManagementUnavailable,
    _canonical,
    _revision,
)
from agent_storage.postgres.work_unit import postgres_transaction_work_unit

CONTRACT = "frontend-profile-management/1"


def publication(profile: FrontendCapabilityProfileVersion | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "frontendAppId": profile.frontend_app_id,
        "profileRevision": profile.revision,
        "profileDigest": profile.profile_digest,
        "lifecycle": profile.lifecycle.value,
    }


class FrontendProfileManagementStore:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._management = HostManagementStore(dsn, deployment_namespace=deployment_namespace)
        self._registry = PostgresClientCapabilityRegistry(
            dsn, deployment_namespace=deployment_namespace
        )

    def read(
        self, trust: HostManagementTrust, approved: FrontendCapabilityProfileVersion
    ) -> dict[str, Any]:
        with self._management.authorized(trust) as connection:
            with postgres_transaction_work_unit(self._registry._database, connection):
                row = self._owner(connection, trust, approved.frontend_app_id)
                result = self._snapshot(
                    connection, trust, approved, 0 if row is None else row["revision"]
                )
                self._management._live(connection, trust)
                return result

    def apply(
        self,
        trust: HostManagementTrust,
        approved: FrontendCapabilityProfileVersion,
        expected: int,
        operation_id: str,
        active: bool,
        mutate: Callable[[], None],
    ) -> dict[str, Any]:
        _revision(expected, maximum=2**53 - 2)
        if str(UUID(operation_id)) != operation_id or type(active) is not bool:
            raise ValueError("invalid operation")
        digest = sha256(
            _canonical(
                {
                    "trust": asdict(trust) | {"expires_at": trust.expires_at.isoformat()},
                    "profile": approved.model_dump(mode="json"),
                    "expected": expected,
                    "active": active,
                }
            ).encode()
        ).hexdigest()
        with self._management.authorized(trust) as connection:
            with postgres_transaction_work_unit(self._registry._database, connection):
                key = (self._management.deployment_namespace, approved.frontend_app_id)
                lock_frontend_app(connection, *key)
                connection.execute(
                    """INSERT INTO frontend_profile_management
                    (deployment_namespace,frontend_app_id,product_id,environment,host_app_id,namespace_id,revision)
                    VALUES (%s,%s,%s,%s,%s,%s,0) ON CONFLICT DO NOTHING""",
                    (
                        *key,
                        trust.product_id,
                        trust.environment,
                        trust.host_app_id,
                        trust.namespace_id,
                    ),
                )
                row = self._owner(connection, trust, approved.frontend_app_id)
                assert row is not None
                receipt = connection.execute(
                    """SELECT * FROM frontend_profile_management_receipts
                    WHERE deployment_namespace=%s AND frontend_app_id=%s AND operation_id=%s""",
                    (*key, operation_id),
                ).fetchone()
                if receipt is not None:
                    if receipt["payload_digest"] != digest:
                        raise HostManagementConflict("Operation payload differs")
                    self._management._live(connection, trust)
                    return {**receipt["result"], "replayed": True}
                if row["revision"] != expected:
                    raise HostManagementConflict("Profile management CAS differs")
                foreign = connection.execute(
                    "SELECT 1 FROM frontend_capability_bindings WHERE deployment_namespace=%s "
                    "AND frontend_app_id=%s AND (host_app_id<>%s OR namespace_id<>%s) LIMIT 1",
                    (*key, trust.host_app_id, trust.namespace_id),
                ).fetchone()
                if foreign is not None:
                    raise HostManagementConflict(
                        "Shared legacy App requires an independent App before scoped changes"
                    )
                count = connection.execute(
                    "SELECT count(*) AS n FROM frontend_profile_management_receipts "
                    "WHERE deployment_namespace=%s AND frontend_app_id=%s",
                    key,
                ).fetchone()
                if count is None or count["n"] >= 4096:
                    raise HostManagementConflict("Profile operation retention limit reached")
                mutate()
                connection.execute(
                    "UPDATE frontend_profile_management SET revision=revision+1 "
                    "WHERE deployment_namespace=%s AND frontend_app_id=%s",
                    key,
                )
                result = self._snapshot(connection, trust, approved, expected + 1)
                connection.execute(
                    """INSERT INTO frontend_profile_management_receipts
                    (deployment_namespace,frontend_app_id,operation_id,payload_digest,trust_revision,fingerprint,result)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (*key, operation_id, digest, trust.revision, trust.fingerprint, Jsonb(result)),
                )
                self._management._live(connection, trust)
                return result

    def _owner(self, connection: Any, trust: HostManagementTrust, app: str) -> Any:
        row = connection.execute(
            "SELECT * FROM frontend_profile_management "
            "WHERE deployment_namespace=%s AND frontend_app_id=%s FOR UPDATE",
            (self._management.deployment_namespace, app),
        ).fetchone()
        if row is not None and any(
            row[field] != getattr(trust, field)
            for field in ("product_id", "environment", "host_app_id", "namespace_id")
        ):
            raise HostManagementUnavailable("Profile belongs to another product scope")
        return row

    def _snapshot(
        self,
        connection: Any,
        trust: HostManagementTrust,
        approved: FrontendCapabilityProfileVersion,
        revision: int,
    ) -> dict[str, Any]:
        connection.execute(
            "SELECT binding_id FROM frontend_capability_bindings WHERE deployment_namespace=%s "
            "AND host_app_id=%s AND namespace_id=%s AND frontend_app_id=%s FOR SHARE",
            (*self._management._binding(trust), approved.frontend_app_id),
        ).fetchall()
        binding = (
            None
            if revision == 0
            else self._registry.get_binding_for_host(
                host_app_id=trust.host_app_id,
                namespace_id=trust.namespace_id,
                frontend_app_id=approved.frontend_app_id,
            )
        )
        connection.execute(
            "SELECT revision FROM frontend_capability_profiles WHERE deployment_namespace=%s "
            "AND frontend_app_id=%s AND revision IN (%s,%s) FOR SHARE",
            (
                self._management.deployment_namespace,
                approved.frontend_app_id,
                approved.revision,
                approved.revision if binding is None else binding.revision,
            ),
        ).fetchall()
        profile = (
            None
            if binding is None
            else self._registry.get_profile(binding.frontend_app_id, binding.revision)
        )
        active = bool(
            profile
            and binding
            and profile.lifecycle is ProfileLifecycle.PUBLISHED
            and profile.profile_digest == approved.profile_digest == binding.profile_digest
        )
        registry = connection.execute(
            "SELECT active FROM host_authority_registries "
            "WHERE deployment_namespace=%s AND host_app_id=%s AND namespace_id=%s FOR SHARE",
            self._management._binding(trust),
        ).fetchone()
        return {
            "contractVersion": CONTRACT,
            "revision": revision,
            "replayed": False,
            "active": active,
            "available": bool(active and registry and registry["active"]),
            "profile": publication(profile),
            "approvedProfile": publication(approved),
            "binding": None
            if binding is None
            else {**binding.model_dump(mode="json"), "binding_digest": binding.binding_digest},
            "observedAt": datetime.now(UTC).isoformat(),
        }
