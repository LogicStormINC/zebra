from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from sqlite3 import Row
from uuid import uuid4

from agent_core.domain.context_continuation import (
    ProviderContinuationArtifact,
    ProviderContinuationRef,
)

from agent_storage.database import SQLiteDatabase


@dataclass(frozen=True)
class LoadedProviderContinuation:
    artifact: ProviderContinuationArtifact
    opaque_payload: bytes


class SQLiteProviderContinuationStore:
    """Tenant-isolated lifecycle store for provider-owned opaque state."""

    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def store(
        self,
        *,
        tenant_id: str,
        session_id: str,
        reference: ProviderContinuationRef,
        opaque_payload: bytes,
        maximum_ttl_seconds: int | None = None,
    ) -> ProviderContinuationArtifact:
        tenant_id = self._required_text(tenant_id, "tenant_id")
        session_id = self._required_text(session_id, "session_id")
        if not opaque_payload:
            raise ValueError("provider continuation payload must not be empty")
        if reference.expires_at is None:
            raise ValueError("durable provider continuation requires an expiry")
        if maximum_ttl_seconds is not None:
            ttl = (reference.expires_at - reference.created_at).total_seconds()
            if ttl > maximum_ttl_seconds:
                raise ValueError("provider continuation exceeds capability TTL")

        artifact = ProviderContinuationArtifact(
            artifact_id=str(uuid4()),
            tenant_id=tenant_id,
            session_id=session_id,
            reference=reference,
            payload_sha256=sha256(opaque_payload).hexdigest(),
            size_bytes=len(opaque_payload),
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO provider_continuation_artifacts (
                    artifact_id, tenant_id, session_id, reference_id, provider,
                    model_name, capability_version, source_hash, opaque_payload,
                    payload_sha256, size_bytes, created_at, expires_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    artifact.artifact_id,
                    tenant_id,
                    session_id,
                    reference.reference_id,
                    reference.provider,
                    reference.model_name,
                    reference.capability_version,
                    reference.source_hash,
                    opaque_payload,
                    artifact.payload_sha256,
                    artifact.size_bytes,
                    reference.created_at.astimezone(UTC).isoformat(),
                    reference.expires_at.astimezone(UTC).isoformat(),
                ),
            )
        return artifact

    def load_compatible(
        self,
        artifact_id: str,
        *,
        tenant_id: str,
        provider: str,
        model_name: str,
        capability_version: str,
        as_of: datetime | None = None,
    ) -> LoadedProviderContinuation | None:
        effective_as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM provider_continuation_artifacts
                WHERE artifact_id = ? AND tenant_id = ?
                """,
                (artifact_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        artifact = self._artifact_from_row(row)
        if not artifact.is_compatible(
            provider=provider,
            model_name=model_name,
            capability_version=capability_version,
            as_of=effective_as_of,
        ):
            return None
        payload = row["opaque_payload"]
        if payload is None or sha256(payload).hexdigest() != artifact.payload_sha256:
            raise ValueError("provider continuation payload failed integrity validation")
        return LoadedProviderContinuation(artifact=artifact, opaque_payload=payload)

    def delete(
        self,
        artifact_id: str,
        *,
        tenant_id: str,
        deleted_at: datetime | None = None,
    ) -> ProviderContinuationArtifact | None:
        timestamp = (deleted_at or datetime.now(UTC)).astimezone(UTC)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM provider_continuation_artifacts
                WHERE artifact_id = ? AND tenant_id = ?
                """,
                (artifact_id, tenant_id),
            ).fetchone()
            if row is None:
                return None
            if row["deleted_at"] is None:
                connection.execute(
                    """
                    UPDATE provider_continuation_artifacts
                    SET opaque_payload = NULL, deleted_at = ?
                    WHERE artifact_id = ? AND tenant_id = ?
                    """,
                    (timestamp.isoformat(), artifact_id, tenant_id),
                )
                row = connection.execute(
                    "SELECT * FROM provider_continuation_artifacts WHERE artifact_id = ?",
                    (artifact_id,),
                ).fetchone()
        return self._artifact_from_row(row)

    def sweep_expired(self, *, as_of: datetime | None = None) -> list[str]:
        timestamp = (as_of or datetime.now(UTC)).astimezone(UTC)
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT artifact_id FROM provider_continuation_artifacts
                WHERE deleted_at IS NULL AND expires_at <= ?
                """,
                (timestamp.isoformat(),),
            ).fetchall()
            artifact_ids = [row["artifact_id"] for row in rows]
            connection.execute(
                """
                UPDATE provider_continuation_artifacts
                SET opaque_payload = NULL, deleted_at = ?
                WHERE deleted_at IS NULL AND expires_at <= ?
                """,
                (timestamp.isoformat(), timestamp.isoformat()),
            )
        return artifact_ids

    @staticmethod
    def _required_text(value: str, field: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field} must not be blank")
        return stripped

    @staticmethod
    def _artifact_from_row(row: Row) -> ProviderContinuationArtifact:
        return ProviderContinuationArtifact(
            artifact_id=row["artifact_id"],
            tenant_id=row["tenant_id"],
            session_id=row["session_id"],
            reference=ProviderContinuationRef(
                reference_id=row["reference_id"],
                provider=row["provider"],
                model_name=row["model_name"],
                capability_version=row["capability_version"],
                source_hash=row["source_hash"],
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
            ),
            payload_sha256=row["payload_sha256"],
            size_bytes=row["size_bytes"],
            deleted_at=(datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None),
        )

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_continuation_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    reference_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    capability_version TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    opaque_payload BLOB,
                    payload_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    deleted_at TEXT,
                    UNIQUE (tenant_id, provider, reference_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_provider_continuations_expiry
                ON provider_continuation_artifacts(expires_at)
                WHERE deleted_at IS NULL
                """
            )
