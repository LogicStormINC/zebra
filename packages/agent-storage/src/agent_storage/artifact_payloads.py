from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadInspection,
    ArtifactPayloadLifecycleStatus,
    ArtifactPayloadStatus,
    ArtifactPayloadWrite,
    StoredArtifactPayload,
)
from agent_core.domain.identifiers import ArtifactId, SessionId, new_artifact_id

from agent_storage.database import SQLiteDatabase


class ArtifactPayloadMissingError(FileNotFoundError):
    """Raised when durable artifact payload metadata exists but the file is missing."""


class SQLiteArtifactPayloadStore:
    def __init__(
        self,
        database_path: str | Path,
        *,
        root_path: str | Path | None = None,
    ) -> None:
        self._database = SQLiteDatabase(database_path)
        default_root = (
            self._database.database_path.parent
            / f"{self._database.database_path.stem}-artifacts"
        )
        self._root = (
            Path(root_path).expanduser().resolve(strict=False)
            if root_path is not None
            else default_root.resolve(strict=False)
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def store_payload(self, payload: ArtifactPayloadWrite) -> StoredArtifactPayload:
        artifact_id = new_artifact_id()
        payload_path = self._payload_path(payload.session_id, artifact_id, payload.file_name)
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_bytes(payload.payload)
        stored = StoredArtifactPayload(
            artifact_id=artifact_id,
            session_id=payload.session_id,
            kind=payload.kind,
            mime_type=payload.mime_type,
            uri=payload_path.resolve(strict=False).as_uri(),
            sha256=sha256(payload.payload).hexdigest(),
            size_bytes=len(payload.payload),
            lifecycle_status=ArtifactPayloadLifecycleStatus.ACTIVE,
            retained_until=payload.retained_until.astimezone(UTC)
            if payload.retained_until is not None
            else None,
            pruned_at=None,
            created_at=payload.created_at.astimezone(UTC),
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO artifact_payloads (
                    artifact_id,
                    session_id,
                    kind,
                    mime_type,
                    uri,
                    sha256,
                    size_bytes,
                    lifecycle_status,
                    retained_until,
                    pruned_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(stored.artifact_id),
                    str(stored.session_id),
                    stored.kind,
                    stored.mime_type,
                    stored.uri,
                    stored.sha256,
                    stored.size_bytes,
                    stored.lifecycle_status.value,
                    (
                        stored.retained_until.isoformat()
                        if stored.retained_until is not None
                        else None
                    ),
                    None,
                    stored.created_at.isoformat(),
                ),
            )
        return stored

    def get_payload(self, artifact_id: ArtifactId) -> StoredArtifactPayload | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    artifact_id,
                    session_id,
                    kind,
                    mime_type,
                    uri,
                    sha256,
                    size_bytes,
                    lifecycle_status,
                    retained_until,
                    pruned_at,
                    created_at
                FROM artifact_payloads
                WHERE artifact_id = ?
                """,
                (str(artifact_id),),
            ).fetchone()
        if row is None:
            return None
        return StoredArtifactPayload(
            artifact_id=ArtifactId(UUID(row["artifact_id"])),
            session_id=SessionId(UUID(row["session_id"])),
            kind=row["kind"],
            mime_type=row["mime_type"],
            uri=row["uri"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            lifecycle_status=ArtifactPayloadLifecycleStatus(row["lifecycle_status"]),
            retained_until=(
                datetime.fromisoformat(row["retained_until"])
                if row["retained_until"] is not None
                else None
            ),
            pruned_at=(
                datetime.fromisoformat(row["pruned_at"])
                if row["pruned_at"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def inspect_payload(self, artifact_id: ArtifactId) -> ArtifactPayloadInspection | None:
        stored = self.get_payload(artifact_id)
        if stored is None:
            return None
        if stored.lifecycle_status is ArtifactPayloadLifecycleStatus.PRUNED:
            status = ArtifactPayloadStatus.PRUNED
        else:
            status = (
                ArtifactPayloadStatus.AVAILABLE
                if self._uri_path(stored.uri).is_file()
                else ArtifactPayloadStatus.MISSING
            )
        return ArtifactPayloadInspection(
            artifact_id=artifact_id,
            status=status,
            payload=stored,
        )

    def prune_payload(
        self,
        artifact_id: ArtifactId,
        *,
        pruned_at: datetime | None = None,
    ) -> StoredArtifactPayload | None:
        stored = self.get_payload(artifact_id)
        if stored is None:
            return None
        if stored.lifecycle_status is ArtifactPayloadLifecycleStatus.PRUNED:
            return stored
        payload_path = self._uri_path(stored.uri)
        if payload_path.exists():
            payload_path.unlink()
        effective_pruned_at = (pruned_at or datetime.now(UTC)).astimezone(UTC)
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE artifact_payloads
                SET lifecycle_status = ?, pruned_at = ?
                WHERE artifact_id = ?
                """,
                (
                    ArtifactPayloadLifecycleStatus.PRUNED.value,
                    effective_pruned_at.isoformat(),
                    str(artifact_id),
                ),
            )
        updated = self.get_payload(artifact_id)
        assert updated is not None
        return updated

    def sweep_expired_payloads(
        self,
        *,
        as_of: datetime | None = None,
    ) -> list[StoredArtifactPayload]:
        effective_as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT artifact_id
                FROM artifact_payloads
                WHERE lifecycle_status = ?
                  AND retained_until IS NOT NULL
                  AND retained_until <= ?
                ORDER BY retained_until, created_at
                """,
                (
                    ArtifactPayloadLifecycleStatus.ACTIVE.value,
                    effective_as_of.isoformat(),
                ),
            ).fetchall()
        pruned: list[StoredArtifactPayload] = []
        for row in rows:
            payload = self.prune_payload(
                ArtifactId(UUID(row["artifact_id"])),
                pruned_at=effective_as_of,
            )
            if payload is not None:
                pruned.append(payload)
        return pruned

    def read_payload_bytes(self, artifact_id: ArtifactId) -> bytes:
        inspection = self.inspect_payload(artifact_id)
        if inspection is None:
            raise ArtifactPayloadMissingError("artifact payload metadata was not found")
        payload_path = self._uri_path(inspection.payload.uri)
        if inspection.status is ArtifactPayloadStatus.PRUNED:
            raise ArtifactPayloadMissingError("artifact payload has been pruned")
        if inspection.status is ArtifactPayloadStatus.MISSING:
            raise ArtifactPayloadMissingError("artifact payload file is missing")
        return payload_path.read_bytes()

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS artifact_payloads (
                    artifact_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    lifecycle_status TEXT NOT NULL DEFAULT 'active',
                    retained_until TEXT,
                    pruned_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(artifact_payloads)"
                ).fetchall()
            }
            if "lifecycle_status" not in columns:
                connection.execute(
                    """
                    ALTER TABLE artifact_payloads
                    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'active'
                    """
                )
            if "retained_until" not in columns:
                connection.execute(
                    """
                    ALTER TABLE artifact_payloads
                    ADD COLUMN retained_until TEXT
                    """
                )
            if "pruned_at" not in columns:
                connection.execute(
                    """
                    ALTER TABLE artifact_payloads
                    ADD COLUMN pruned_at TEXT
                    """
                )

    def _payload_path(
        self,
        session_id: SessionId,
        artifact_id: ArtifactId,
        file_name: str | None,
    ) -> Path:
        suffix = Path(file_name).suffix if file_name is not None else ".bin"
        return self._root / str(session_id) / str(artifact_id) / f"payload{suffix}"

    def _uri_path(self, uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ArtifactPayloadMissingError("artifact payload uri is not a local file uri")
        return Path(parsed.path)
