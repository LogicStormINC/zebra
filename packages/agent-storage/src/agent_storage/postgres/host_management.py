"""Short, namespace-bound Host management transactions; no startup DDL or retries."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.host_auth import HostRegistryRecord, _registry_from_row

_MAX_REVISION = 2**53 - 1
_BINDING_WHERE = "deployment_namespace=%s AND host_app_id=%s AND namespace_id=%s"


class HostManagementConflict(ValueError):
    """The caller's CAS revision or operation payload no longer matches."""


class HostManagementUnavailable(PermissionError):
    """Current shared approval is missing, stale or has a different scope."""


class HostManagementExpired(PermissionError):
    """The credential's approval deadline has elapsed."""


@dataclass(frozen=True)
class HostManagementTrust:
    deployment_id: str
    audience: str
    product_id: str
    environment: str
    host_app_id: str
    namespace_id: str
    revision: int
    fingerprint: str
    expires_at: datetime

    def __post_init__(self) -> None:
        for name, maximum in (
            ("deployment_id", 255),
            ("audience", 512),
            ("product_id", 128),
            ("environment", 128),
            ("host_app_id", 128),
            ("namespace_id", 512),
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > maximum
            ):
                raise ValueError(f"{name} must be nonblank, trimmed and bounded")
        _revision(self.revision, minimum=1)
        if (
            not isinstance(self.fingerprint, str)
            or len(self.fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in self.fingerprint)
        ):
            raise ValueError("fingerprint must be a lowercase SHA-256 digest")
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")


@dataclass(frozen=True)
class ManagedHostRegistry:
    record: HostRegistryRecord | None
    revision: int
    replayed: bool = False


class HostManagementStore:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def approve(self, trust: HostManagementTrust, expected_revision: int) -> None:
        _revision(expected_revision, maximum=_MAX_REVISION - 1)
        if trust.revision != expected_revision + 1:
            raise HostManagementConflict("Approval must advance exactly one revision")
        with self._locked(trust) as connection:
            row = connection.execute(
                f"SELECT * FROM host_management_approvals WHERE {_BINDING_WHERE} FOR UPDATE",
                self._binding(trust),
            ).fetchone()
            if (0 if row is None else row["revision"]) != expected_revision:
                raise HostManagementConflict("Approval revision changed")
            if row is not None and not _same_scope(row, trust):
                raise HostManagementConflict("Approved scope is immutable")
            self._live(connection, trust)
            connection.execute(
                """
                INSERT INTO host_management_approvals (
                    deployment_namespace, host_app_id, namespace_id,
                    deployment_id, audience, product_id, environment,
                    revision, fingerprint, expires_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (deployment_namespace,host_app_id,namespace_id)
                DO UPDATE SET revision=EXCLUDED.revision, fingerprint=EXCLUDED.fingerprint,
                    expires_at=EXCLUDED.expires_at, updated_at=clock_timestamp()
                """,
                (
                    *self._binding(trust),
                    trust.deployment_id,
                    trust.audience,
                    trust.product_id,
                    trust.environment,
                    trust.revision,
                    trust.fingerprint,
                    trust.expires_at,
                ),
            )
            self._audit(connection, trust, "approve")
            self._live(connection, trust)

    def read(self, trust: HostManagementTrust) -> ManagedHostRegistry:
        with self._locked(trust) as connection:
            self._authorize(connection, trust)
            row = connection.execute(
                f"SELECT * FROM host_authority_registries WHERE {_BINDING_WHERE} FOR SHARE",
                self._binding(trust),
            ).fetchone()
            self._live(connection, trust)
            return _snapshot(row)

    def apply(
        self,
        trust: HostManagementTrust,
        record: HostRegistryRecord,
        expected_revision: int,
        operation_id: str,
    ) -> ManagedHostRegistry:
        _revision(expected_revision, maximum=_MAX_REVISION - 1)
        if not isinstance(operation_id, str) or str(UUID(operation_id)) != operation_id:
            raise ValueError("operation_id must be a canonical UUID")
        if (record.host_app_id, record.namespace_id) != (trust.host_app_id, trust.namespace_id):
            raise HostManagementUnavailable("Registry binding differs from approval")
        payload = {
            "trust_revision": trust.revision,
            "fingerprint": trust.fingerprint,
            "expected_revision": expected_revision,
            "registry": asdict(record),
        }
        digest = sha256(_canonical(payload).encode()).hexdigest()
        with self._locked(trust) as connection:
            self._authorize(connection, trust)
            receipt = connection.execute(
                f"SELECT * FROM host_management_receipts WHERE {_BINDING_WHERE} "
                "AND operation_id=%s",
                (*self._binding(trust), operation_id),
            ).fetchone()
            if receipt is not None:
                if receipt["payload_digest"] != digest:
                    raise HostManagementConflict("Operation was used with a different payload")
                self._live(connection, trust)
                return ManagedHostRegistry(
                    _registry_from_row(receipt["registry"]), int(receipt["revision"]), True
                )
            row = connection.execute(
                f"SELECT * FROM host_authority_registries WHERE {_BINDING_WHERE} FOR UPDATE",
                self._binding(trust),
            ).fetchone()
            self._live(connection, trust)
            if (0 if row is None else row["revision"]) != expected_revision:
                raise HostManagementConflict("Registry revision changed")
            values = (
                record.issuer,
                record.audience,
                record.jwks_uri,
                Jsonb(list(record.allowed_origins)),
                Jsonb(list(record.algorithms)),
                record.policy_version,
                record.active,
            )
            if row is None:
                changed = connection.execute(
                    """
                    INSERT INTO host_authority_registries (
                        deployment_namespace,host_app_id,namespace_id,issuer,audience,jwks_uri,
                        allowed_origins,algorithms,policy_version,active
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (deployment_namespace,host_app_id,namespace_id) DO NOTHING
                    RETURNING *
                    """,
                    (*self._binding(trust), *values),
                ).fetchone()
            else:
                changed = connection.execute(
                    f"""
                    UPDATE host_authority_registries SET issuer=%s,audience=%s,jwks_uri=%s,
                        allowed_origins=%s,algorithms=%s,policy_version=%s,active=%s,
                        revision=revision+1,updated_at=clock_timestamp()
                    WHERE {_BINDING_WHERE} AND revision=%s RETURNING *
                    """,
                    (*values, *self._binding(trust), expected_revision),
                ).fetchone()
            if changed is None:
                raise HostManagementConflict("Registry changed during creation")
            self._live(connection, trust)
            revision = int(changed["revision"])
            connection.execute(
                """
                INSERT INTO host_management_receipts (
                    deployment_namespace,host_app_id,namespace_id,operation_id,
                    payload_digest,registry,revision
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (*self._binding(trust), operation_id, digest, Jsonb(asdict(record)), revision),
            )
            self._audit(connection, trust, "apply", revision, operation_id)
            self._live(connection, trust)
            return _snapshot(changed)

    @contextmanager
    def _locked(self, trust: HostManagementTrust) -> Any:
        remaining = (trust.expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise HostManagementExpired("Host management approval expired")
        deadline = min(monotonic() + 5, monotonic() + remaining)
        with self._database.connect_task_io(deadline=deadline) as connection:
            # Metadata locks share the existing hard I/O deadline, including COMMIT.
            connection.execute("SELECT set_config('lock_timeout','0',true)")
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (_canonical(self._binding(trust)),),
            )
            self._live(connection, trust)
            yield connection

    def _binding(self, trust: HostManagementTrust) -> tuple[str, str, str]:
        return self.deployment_namespace, trust.host_app_id, trust.namespace_id

    def _authorize(self, connection: Any, trust: HostManagementTrust) -> None:
        row = connection.execute(
            f"SELECT * FROM host_management_approvals WHERE {_BINDING_WHERE} FOR SHARE",
            self._binding(trust),
        ).fetchone()
        if (
            row is None
            or not _same_scope(row, trust)
            or row["revision"] != trust.revision
            or row["fingerprint"] != trust.fingerprint
            or row["expires_at"] != trust.expires_at
        ):
            raise HostManagementUnavailable("Current Host management approval does not match")
        self._live(connection, trust)

    @staticmethod
    def _live(connection: Any, trust: HostManagementTrust) -> None:
        row = connection.execute("SELECT clock_timestamp() AS now").fetchone()
        if row is None or row["now"] >= trust.expires_at:
            raise HostManagementExpired("Host management approval expired")

    def _audit(
        self,
        connection: Any,
        trust: HostManagementTrust,
        action: str,
        revision: int | None = None,
        operation_id: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO host_management_audit (
                deployment_namespace,host_app_id,namespace_id,action,
                trust_revision,fingerprint,registry_revision,operation_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                *self._binding(trust),
                action,
                trust.revision,
                trust.fingerprint,
                revision,
                operation_id,
            ),
        )


def _same_scope(row: dict[str, Any], trust: HostManagementTrust) -> bool:
    return all(
        row[name] == getattr(trust, name)
        for name in (
            "deployment_id",
            "audience",
            "product_id",
            "environment",
            "host_app_id",
            "namespace_id",
        )
    )


def _snapshot(row: dict[str, Any] | None) -> ManagedHostRegistry:
    return (
        ManagedHostRegistry(None, 0)
        if row is None
        else ManagedHostRegistry(
            _registry_from_row(row),
            int(row["revision"]),
        )
    )


def _revision(value: int, *, minimum: int = 0, maximum: int = _MAX_REVISION) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Revision must be a bounded integer")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
