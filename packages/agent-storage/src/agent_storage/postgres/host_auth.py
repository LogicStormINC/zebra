"""Namespace-bound PostgreSQL Host registry and replay evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase

HostGrantOutcome = Literal["accepted", "replay", "rejected"]
_ALGORITHMS = frozenset({"RS256", "ES256"})


class HostAuthorityStorageError(ValueError):
    """Base error for invalid or untrusted Host authority storage inputs."""


class HostRegistryBindingError(HostAuthorityStorageError):
    """Raised when a registry binding is missing or inactive."""


@dataclass(frozen=True)
class HostRegistryRecord:
    """One issuer and tenant binding scoped to one Zebra deployment."""

    host_app_id: str
    namespace_id: str
    issuer: str
    audience: str
    jwks_uri: str
    allowed_origins: tuple[str, ...]
    algorithms: tuple[str, ...]
    policy_version: str
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "host_app_id", _text(self.host_app_id, "host_app_id", 128))
        object.__setattr__(self, "namespace_id", _text(self.namespace_id, "namespace_id", 512))
        object.__setattr__(self, "issuer", _https_origin(self.issuer, "issuer"))
        object.__setattr__(self, "audience", _text(self.audience, "audience", 512))
        object.__setattr__(self, "jwks_uri", _https_url(self.jwks_uri, "jwks_uri"))
        object.__setattr__(
            self,
            "allowed_origins",
            _origins(self.allowed_origins),
        )
        object.__setattr__(self, "algorithms", _algorithms(self.algorithms))
        object.__setattr__(
            self, "policy_version", _text(self.policy_version, "policy_version", 128)
        )
        if not isinstance(self.active, bool):
            raise HostAuthorityStorageError("active must be a boolean")


@dataclass(frozen=True)
class HostGrantAttempt:
    """Secret-free values supplied after JWT verification and token digesting."""

    issuer: str
    jti: str
    host_app_id: str
    namespace_id: str
    algorithm: str
    grant_digest: str
    scopes_digest: str
    resource_digest: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "issuer", _https_origin(self.issuer, "issuer"))
        object.__setattr__(self, "jti", _text(self.jti, "jti", 512))
        object.__setattr__(self, "host_app_id", _text(self.host_app_id, "host_app_id", 128))
        object.__setattr__(self, "namespace_id", _text(self.namespace_id, "namespace_id", 512))
        algorithm = _text(self.algorithm, "algorithm", 16)
        if algorithm not in _ALGORITHMS:
            raise HostAuthorityStorageError("algorithm must be RS256 or ES256")
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "grant_digest", _digest(self.grant_digest, "grant_digest"))
        object.__setattr__(self, "scopes_digest", _digest(self.scopes_digest, "scopes_digest"))
        object.__setattr__(
            self, "resource_digest", _digest(self.resource_digest, "resource_digest")
        )
        if self.expires_at.tzinfo is None:
            raise HostAuthorityStorageError("expires_at must be timezone-aware")


@dataclass(frozen=True)
class HostGrantAuditRecord:
    """A bounded audit row; no token or signing material is represented."""

    audit_id: int
    issuer: str
    jti: str
    host_app_id: str
    namespace_id: str
    algorithm: str
    outcome: HostGrantOutcome
    reason: str
    grant_digest: str
    scopes_digest: str
    resource_digest: str
    observed_at: datetime


@dataclass(frozen=True)
class HostGrantReplayDecision:
    """The atomic replay decision and its corresponding audit evidence."""

    accepted: bool
    outcome: HostGrantOutcome
    audit: HostGrantAuditRecord


class PostgresHostAuthorityStore:
    """Persist Host registry, replay and audit rows under one deployment namespace."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def upsert_registry(self, record: HostRegistryRecord) -> HostRegistryRecord:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            row = connection.execute(
                """
                INSERT INTO host_authority_registries (
                    deployment_namespace, host_app_id, namespace_id, issuer,
                    audience, jwks_uri, allowed_origins, algorithms,
                    policy_version, active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, host_app_id, namespace_id)
                DO UPDATE SET issuer = EXCLUDED.issuer,
                    audience = EXCLUDED.audience,
                    jwks_uri = EXCLUDED.jwks_uri,
                    allowed_origins = EXCLUDED.allowed_origins,
                    algorithms = EXCLUDED.algorithms,
                    policy_version = EXCLUDED.policy_version,
                    active = EXCLUDED.active,
                    updated_at = transaction_timestamp()
                RETURNING host_app_id, namespace_id, issuer, audience, jwks_uri,
                    allowed_origins, algorithms, policy_version, active
                """,
                (
                    namespace,
                    record.host_app_id,
                    record.namespace_id,
                    record.issuer,
                    record.audience,
                    record.jwks_uri,
                    Jsonb(list(record.allowed_origins)),
                    Jsonb(list(record.algorithms)),
                    record.policy_version,
                    record.active,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("Host registry upsert returned no row")
        return _registry_from_row(row)

    def get_registry(self, *, host_app_id: str, namespace_id: str) -> HostRegistryRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT host_app_id, namespace_id, issuer, audience, jwks_uri,
                    allowed_origins, algorithms, policy_version, active
                FROM host_authority_registries
                WHERE deployment_namespace = %s
                  AND host_app_id = %s AND namespace_id = %s
                """,
                (self.deployment_namespace, host_app_id, namespace_id),
            ).fetchone()
        return None if row is None else _registry_from_row(row)

    def consume_grant(self, attempt: HostGrantAttempt) -> HostGrantReplayDecision:
        """Atomically consume a jti and append accepted/replay/rejected audit."""
        with self._database.connect() as connection:
            registry = connection.execute(
                """
                SELECT active, algorithms
                FROM host_authority_registries
                WHERE deployment_namespace = %s AND host_app_id = %s
                  AND namespace_id = %s AND issuer = %s
                """,
                (
                    self.deployment_namespace,
                    attempt.host_app_id,
                    attempt.namespace_id,
                    attempt.issuer,
                ),
            ).fetchone()
            if registry is None:
                return self._rejected(
                    connection, attempt, "Host registry binding is not registered"
                )
            if not registry["active"]:
                return self._rejected(connection, attempt, "Host registry binding is inactive")
            registered_algorithms = tuple(str(value) for value in registry["algorithms"])
            if attempt.algorithm not in registered_algorithms:
                return self._rejected(connection, attempt, "JWT algorithm is not registered")
            now = connection.execute("SELECT transaction_timestamp() AS now").fetchone()
            if now is None or attempt.expires_at <= now["now"]:
                return self._rejected(connection, attempt, "Host Grant is expired")
            inserted = connection.execute(
                """
                INSERT INTO host_grant_replay_ledger (
                    deployment_namespace, issuer, jti, host_app_id, namespace_id,
                    algorithm, grant_digest, scopes_digest, resource_digest, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, issuer, jti) DO NOTHING
                RETURNING seen_at
                """,
                (
                    self.deployment_namespace,
                    attempt.issuer,
                    attempt.jti,
                    attempt.host_app_id,
                    attempt.namespace_id,
                    attempt.algorithm,
                    attempt.grant_digest,
                    attempt.scopes_digest,
                    attempt.resource_digest,
                    attempt.expires_at,
                ),
            ).fetchone()
            outcome: HostGrantOutcome = "accepted" if inserted is not None else "replay"
            reason = "jti accepted" if inserted is not None else "jti replay rejected"
            audit = self._insert_audit(connection, attempt, outcome, reason)
            return HostGrantReplayDecision(inserted is not None, outcome, audit)

    def list_audit(self, *, issuer: str, jti: str) -> tuple[HostGrantAuditRecord, ...]:
        issuer = _https_origin(issuer, "issuer")
        jti = _text(jti, "jti", 512)
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT audit_id, issuer, jti, host_app_id, namespace_id, algorithm,
                    outcome, reason, grant_digest, scopes_digest, resource_digest,
                    observed_at
                FROM host_grant_audit
                WHERE deployment_namespace = %s AND issuer = %s AND jti = %s
                ORDER BY audit_id
                """,
                (self.deployment_namespace, issuer, jti),
            ).fetchall()
        return tuple(_audit_from_row(row) for row in rows)

    def _rejected(
        self, connection: Any, attempt: HostGrantAttempt, reason: str
    ) -> HostGrantReplayDecision:
        audit = self._insert_audit(connection, attempt, "rejected", reason)
        return HostGrantReplayDecision(False, "rejected", audit)

    def _insert_audit(
        self,
        connection: Any,
        attempt: HostGrantAttempt,
        outcome: HostGrantOutcome,
        reason: str,
    ) -> HostGrantAuditRecord:
        row = connection.execute(
            """
            INSERT INTO host_grant_audit (
                deployment_namespace, issuer, jti, host_app_id, namespace_id,
                algorithm, outcome, reason, grant_digest, scopes_digest, resource_digest
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING audit_id, issuer, jti, host_app_id, namespace_id, algorithm,
                outcome, reason, grant_digest, scopes_digest, resource_digest, observed_at
            """,
            (
                self.deployment_namespace,
                attempt.issuer,
                attempt.jti,
                attempt.host_app_id,
                attempt.namespace_id,
                attempt.algorithm,
                outcome,
                _text(reason, "reason", 512),
                attempt.grant_digest,
                attempt.scopes_digest,
                attempt.resource_digest,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Host Grant audit insert returned no row")
        return _audit_from_row(row)


def _text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise HostAuthorityStorageError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise HostAuthorityStorageError(f"{field_name} must be non-blank and bounded")
    return normalized


def _unique(values: Iterable[str], field_name: str, maximum: int) -> tuple[str, ...]:
    if isinstance(values, str):
        raise HostAuthorityStorageError(f"{field_name} must be a sequence")
    normalized = tuple(_text(value, field_name, maximum) for value in values)
    if not normalized or len(set(normalized)) != len(normalized):
        raise HostAuthorityStorageError(f"{field_name} must contain unique values")
    return normalized


def _origins(values: Iterable[str]) -> tuple[str, ...]:
    origins = tuple(_https_origin(value, "allowed_origin") for value in values)
    if not origins or len(set(origins)) != len(origins):
        raise HostAuthorityStorageError("allowed_origins must contain unique values")
    return origins


def _algorithms(values: Iterable[str]) -> tuple[str, ...]:
    algorithms = _unique(values, "algorithm", 16)
    if not set(algorithms) <= _ALGORITHMS:
        raise HostAuthorityStorageError("algorithms must use RS256 or ES256")
    return algorithms


def _digest(value: str, field_name: str) -> str:
    normalized = _text(value, field_name, 64).lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise HostAuthorityStorageError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _https_origin(value: str, field_name: str) -> str:
    normalized = _text(value, field_name, 2_048)
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        raise HostAuthorityStorageError(f"{field_name} must be an HTTPS origin")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise HostAuthorityStorageError(f"{field_name} must not contain credentials or suffixes")
    host = parsed.hostname
    if host is None:
        raise HostAuthorityStorageError(f"{field_name} must contain a host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HostAuthorityStorageError(f"{field_name} has an invalid port") from exc
    return f"https://{host.lower()}{f':{port}' if port is not None else ''}"


def _https_url(value: str, field_name: str) -> str:
    normalized = _text(value, field_name, 2_048)
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HostAuthorityStorageError(f"{field_name} must be an HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise HostAuthorityStorageError(f"{field_name} must not contain credentials")
    return normalized


def _registry_from_row(row: dict[str, Any]) -> HostRegistryRecord:
    return HostRegistryRecord(
        host_app_id=str(row["host_app_id"]),
        namespace_id=str(row["namespace_id"]),
        issuer=str(row["issuer"]),
        audience=str(row["audience"]),
        jwks_uri=str(row["jwks_uri"]),
        allowed_origins=tuple(str(value) for value in row["allowed_origins"]),
        algorithms=tuple(str(value) for value in row["algorithms"]),
        policy_version=str(row["policy_version"]),
        active=bool(row["active"]),
    )


def _audit_from_row(row: dict[str, Any]) -> HostGrantAuditRecord:
    observed_at = row["observed_at"]
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise HostAuthorityStorageError("audit observed_at must be timezone-aware")
    outcome = str(row["outcome"])
    if outcome not in {"accepted", "replay", "rejected"}:
        raise HostAuthorityStorageError("audit outcome is invalid")
    return HostGrantAuditRecord(
        audit_id=int(row["audit_id"]),
        issuer=str(row["issuer"]),
        jti=str(row["jti"]),
        host_app_id=str(row["host_app_id"]),
        namespace_id=str(row["namespace_id"]),
        algorithm=str(row["algorithm"]),
        outcome=outcome,  # type: ignore[arg-type]
        reason=str(row["reason"]),
        grant_digest=str(row["grant_digest"]),
        scopes_digest=str(row["scopes_digest"]),
        resource_digest=str(row["resource_digest"]),
        observed_at=observed_at.astimezone(UTC),
    )
