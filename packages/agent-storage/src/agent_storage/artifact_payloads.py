from __future__ import annotations

import os
import sqlite3
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
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort

from agent_storage.database import SQLiteDatabase, ensure_column


class ArtifactPayloadMissingError(FileNotFoundError):
    """Raised when durable artifact payload metadata exists but the file is missing."""


class SQLiteArtifactPayloadStore(ArtifactPayloadStorePort):
    def __init__(
        self,
        database_path: str | Path,
        *,
        root_path: str | Path | None = None,
    ) -> None:
        self._database = SQLiteDatabase(database_path)
        default_root = (
            self._database.database_path.parent / f"{self._database.database_path.stem}-artifacts"
        )
        self._root = (
            Path(root_path).expanduser().resolve(strict=False)
            if root_path is not None
            else default_root.resolve(strict=False)
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def store_payload(
        self,
        payload: ArtifactPayloadWrite,
        *,
        artifact_id: ArtifactId | None = None,
    ) -> StoredArtifactPayload:
        artifact_id = artifact_id or new_artifact_id()
        return self.store_payload_immutable(payload, artifact_id=artifact_id)

    def store_payload_immutable(
        self,
        payload: ArtifactPayloadWrite,
        *,
        artifact_id: ArtifactId,
    ) -> StoredArtifactPayload:
        payload_path = self._payload_path(payload.session_id, artifact_id, payload.file_name)
        stored = StoredArtifactPayload(
            artifact_id=artifact_id,
            session_id=payload.session_id,
            kind=payload.kind,
            mime_type=payload.mime_type,
            uri=f"artifact://{artifact_id}",
            access_uri=payload_path.resolve(strict=False).as_uri(),
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
            # ponytail: one database writer lock covers all IDs; scale via cloud reservations.
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_payload(connection, artifact_id)
            if existing is not None:
                comparable = existing.model_copy(
                    update={
                        "uri": stored.uri,
                        "access_uri": self._stored_payload_path(existing).resolve().as_uri(),
                    }
                )
                filename = connection.execute(
                    """SELECT file_name,file_name_recorded FROM artifact_payloads
                       WHERE artifact_id=?""",
                    (str(artifact_id),),
                ).fetchone()
                if comparable != stored or (
                    filename["file_name_recorded"] and filename["file_name"] != payload.file_name
                ):
                    raise ValueError("artifact payload immutable metadata conflicts")
                self._verify_payload_bytes(existing, max_bytes=stored.size_bytes)
                if not filename["file_name_recorded"]:
                    # ponytail: old schemas discarded the basename; bind the first
                    # byte/path/metadata-verified retry, then enforce exact filenames.
                    connection.execute(
                        """UPDATE artifact_payloads SET file_name=?,file_name_recorded=1
                           WHERE artifact_id=?""",
                        (payload.file_name, str(artifact_id)),
                    )
                return existing
            # A crashed publisher may leave bytes without a row. Never replace them,
            # including same-ID orphans under another session or filename suffix.
            # ponytail: scan session directories; cloud reservations index orphan identities.
            for directory in self._root.glob(f"*/{artifact_id}"):
                for orphan in directory.iterdir():
                    if orphan != payload_path:
                        raise ValueError("artifact payload orphan identity conflicts")
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with payload_path.open("xb") as stream:
                    if stream.write(payload.payload) != len(payload.payload):
                        raise OSError("artifact payload write was incomplete")
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                self._verify_payload_bytes(stored, max_bytes=stored.size_bytes)
            connection.execute(
                """
                INSERT INTO artifact_payloads (
                    artifact_id,
                    session_id,
                    kind,
                    mime_type,
                    uri,
                    access_uri,
                    sha256,
                    size_bytes,
                    lifecycle_status,
                    retained_until,
                    pruned_at,
                    created_at
                    ,file_name,file_name_recorded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,1)
                """,
                (
                    str(stored.artifact_id),
                    str(stored.session_id),
                    stored.kind,
                    stored.mime_type,
                    stored.uri,
                    stored.access_uri,
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
                    payload.file_name,
                ),
            )
        return stored

    def get_payload(self, artifact_id: ArtifactId) -> StoredArtifactPayload | None:
        with self._database.connect() as connection:
            return self._get_payload(connection, artifact_id)

    def _get_payload(
        self, connection: sqlite3.Connection, artifact_id: ArtifactId
    ) -> StoredArtifactPayload | None:
        row = connection.execute(
            """
                SELECT
                    artifact_id,
                    session_id,
                    kind,
                    mime_type,
                    uri,
                    access_uri,
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
            access_uri=row["access_uri"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            lifecycle_status=ArtifactPayloadLifecycleStatus(row["lifecycle_status"]),
            retained_until=(
                datetime.fromisoformat(row["retained_until"])
                if row["retained_until"] is not None
                else None
            ),
            pruned_at=(
                datetime.fromisoformat(row["pruned_at"]) if row["pruned_at"] is not None else None
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
                if self._stored_payload_path(stored).is_file()
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
        effective_pruned_at = (pruned_at or datetime.now(UTC)).astimezone(UTC)
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stored = self._get_payload(connection, artifact_id)
            if stored is None:
                return None
            if stored.lifecycle_status is ArtifactPayloadLifecycleStatus.PRUNED:
                self._stored_payload_path(stored).unlink(missing_ok=True)
                return stored
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
        # Durable unreadable state precedes physical removal. A crash leaves only
        # a reclaimable PRUNED file, never ACTIVE metadata pointing at removed bytes.
        self._stored_payload_path(stored).unlink(missing_ok=True)
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
                WHERE (lifecycle_status = ?
                  AND retained_until IS NOT NULL
                  AND retained_until <= ?) OR lifecycle_status = ?
                ORDER BY retained_until, created_at
                """,
                (
                    ArtifactPayloadLifecycleStatus.ACTIVE.value,
                    effective_as_of.isoformat(),
                    ArtifactPayloadLifecycleStatus.PRUNED.value,
                ),
            ).fetchall()
        pruned: list[StoredArtifactPayload] = []
        for row in rows:
            existing = self.get_payload(ArtifactId(UUID(row["artifact_id"])))
            if (
                existing is not None
                and existing.lifecycle_status is ArtifactPayloadLifecycleStatus.PRUNED
                and not self._stored_payload_path(existing).exists()
            ):
                continue
            payload = self.prune_payload(
                ArtifactId(UUID(row["artifact_id"])),
                pruned_at=effective_as_of,
            )
            if payload is not None:
                pruned.append(payload)
        return pruned

    def read_payload_bytes(self, artifact_id: ArtifactId) -> bytes:
        stored = self.get_payload(artifact_id)
        if stored is None:
            raise ArtifactPayloadMissingError("artifact payload metadata was not found")
        return self.read_payload_bytes_bounded(artifact_id, max_bytes=stored.size_bytes)

    def read_payload_bytes_bounded(self, artifact_id: ArtifactId, *, max_bytes: int) -> bytes:
        self._validate_limit(max_bytes)
        inspection = self.inspect_payload(artifact_id)
        if inspection is None:
            raise ArtifactPayloadMissingError("artifact payload metadata was not found")
        if inspection.status is ArtifactPayloadStatus.PRUNED:
            raise ArtifactPayloadMissingError("artifact payload has been pruned")
        if inspection.status is ArtifactPayloadStatus.MISSING:
            raise ArtifactPayloadMissingError("artifact payload file is missing")
        return self._verify_payload_bytes(inspection.payload, max_bytes=max_bytes)

    @staticmethod
    def _validate_limit(max_bytes: int) -> None:
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("max_bytes must be a non-negative integer")

    def _verify_payload_bytes(self, stored: StoredArtifactPayload, *, max_bytes: int) -> bytes:
        self._validate_limit(max_bytes)
        if type(stored.size_bytes) is not int or not 0 <= stored.size_bytes <= max_bytes:
            raise ValueError("artifact payload exceeds byte limit or has invalid length")
        with self._stored_payload_path(stored).open("rb") as stream:
            body = stream.read(max_bytes + 1)
        if len(body) != stored.size_bytes or sha256(body).hexdigest() != stored.sha256:
            raise ValueError("artifact payload bytes do not match immutable metadata")
        return body

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
            ensure_column(
                connection,
                "artifact_payloads",
                "lifecycle_status",
                "TEXT NOT NULL DEFAULT 'active'",
            )
            ensure_column(connection, "artifact_payloads", "retained_until", "TEXT")
            ensure_column(connection, "artifact_payloads", "pruned_at", "TEXT")
            ensure_column(connection, "artifact_payloads", "access_uri", "TEXT")
            ensure_column(connection, "artifact_payloads", "file_name", "TEXT")
            ensure_column(
                connection, "artifact_payloads", "file_name_recorded", "INTEGER NOT NULL DEFAULT 0"
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

    def _stored_payload_path(self, stored: StoredArtifactPayload) -> Path:
        """Resolve the local file path for a stored payload.

        CTX-ART-02: prefers ``access_uri`` (the volatile file:// locator); falls
        back to ``uri`` for legacy rows that still store file:// in ``uri``.
        """
        if stored.access_uri is not None:
            return self._uri_path(stored.access_uri)
        return self._uri_path(stored.uri)
