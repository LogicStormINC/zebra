from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from sqlite3 import Connection
from uuid import UUID

from agent_core.contracts.events import ContextCapsuleCreatedPayload
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    validate_context_capsule,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId, new_artifact_id

from agent_storage.database import SQLiteDatabase
from agent_storage.event_rows import serialize_event_payload


class ActiveContextProjectionConflictError(RuntimeError):
    """Raised when another writer advanced the active capsule first."""


class ImmutableContextCapsuleConflictError(RuntimeError):
    """Raised when a capsule id is reused for different immutable content."""


@dataclass(frozen=True)
class StoredContextCapsule:
    artifact_id: ArtifactId
    session_id: SessionId
    capsule: ContextCapsule
    payload_sha256: str
    event: SessionEvent
    compaction_event: SessionEvent | None = None


class SQLiteContextLifecycleStore:
    """Atomically persist a canonical capsule, its event, and active pointer."""

    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def persist_capsule_and_advance(
        self,
        *,
        session_id: SessionId,
        capsule: ContextCapsule,
        validation_context: ContextCapsuleValidationContext,
        sequence: int,
        expected_active_capsule_id: str | None,
        compaction_event: SessionEvent | None = None,
        created_at: datetime | None = None,
    ) -> StoredContextCapsule:
        validate_context_capsule(capsule, validation_context)
        if capsule.source_event_range is None:
            raise ValueError("an active context capsule requires a source event range")

        timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)
        artifact_id = new_artifact_id()
        payload = capsule.model_dump_json().encode("utf-8")
        payload_sha256 = sha256(payload).hexdigest()
        if compaction_event is not None:
            if compaction_event.session_id != session_id:
                raise ValueError("compaction event session does not match capsule")
            if compaction_event.sequence != sequence:
                raise ValueError("compaction event sequence does not match transaction")
        event = SessionEvent.create(
            session_id=session_id,
            sequence=sequence + (1 if compaction_event is not None else 0),
            event_type=EventType.CONTEXT_CAPSULE_CREATED,
            actor=EventActor.SYSTEM,
            payload=ContextCapsuleCreatedPayload(
                capsule_id=capsule.capsule_id,
                artifact_id=str(artifact_id),
                schema_version=capsule.version,
                source_hash=capsule.source_hash,
                source_event_range=capsule.source_event_range,
                previous_capsule_id=expected_active_capsule_id,
            ).model_dump(mode="json"),
            idempotency_key=f"context-capsule:{capsule.capsule_id}",
            model_profile=capsule.model_profile,
            created_at=timestamp,
        )

        with self._database.connect() as connection:
            active_row = connection.execute(
                "SELECT capsule_id FROM active_context_projections WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
            active_id = active_row["capsule_id"] if active_row is not None else None
            existing = connection.execute(
                """
                SELECT artifact_id, session_id, payload, payload_sha256, event_id
                FROM context_capsule_artifacts WHERE capsule_id = ?
                """,
                (capsule.capsule_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] != payload_sha256:
                    raise ImmutableContextCapsuleConflictError(
                        "capsule id already belongs to different immutable content"
                    )
                self._validate_payload_integrity(existing["payload"], existing["payload_sha256"])
                if active_id != capsule.capsule_id:
                    raise ActiveContextProjectionConflictError(
                        "immutable capsule exists but is no longer the active projection"
                    )
                stored_event = self._event_for_id(connection, existing["event_id"])
                return StoredContextCapsule(
                    artifact_id=ArtifactId(UUID(existing["artifact_id"])),
                    session_id=SessionId(UUID(existing["session_id"])),
                    capsule=ContextCapsule.model_validate_json(existing["payload"]),
                    payload_sha256=existing["payload_sha256"],
                    event=stored_event,
                    compaction_event=compaction_event,
                )
            if active_id != expected_active_capsule_id:
                raise ActiveContextProjectionConflictError(
                    f"active capsule changed from {expected_active_capsule_id!r} to {active_id!r}"
                )

            if compaction_event is not None:
                self._insert_event(connection, compaction_event)
            connection.execute(
                """
                INSERT INTO context_capsule_artifacts (
                    capsule_id, artifact_id, session_id, payload, payload_sha256,
                    source_hash, created_at, event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capsule.capsule_id,
                    str(artifact_id),
                    str(session_id),
                    payload,
                    payload_sha256,
                    capsule.source_hash,
                    timestamp.isoformat(),
                    str(event.event_id),
                ),
            )
            self._insert_event(connection, event)
            connection.execute(
                """
                INSERT INTO active_context_projections (
                    session_id, capsule_id, artifact_id, source_hash,
                    event_sequence, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    capsule_id = excluded.capsule_id,
                    artifact_id = excluded.artifact_id,
                    source_hash = excluded.source_hash,
                    event_sequence = excluded.event_sequence,
                    updated_at = excluded.updated_at
                """,
                (
                    str(session_id),
                    capsule.capsule_id,
                    str(artifact_id),
                    capsule.source_hash,
                    event.sequence,
                    timestamp.isoformat(),
                ),
            )
        return StoredContextCapsule(
            artifact_id=artifact_id,
            session_id=session_id,
            capsule=capsule,
            payload_sha256=payload_sha256,
            event=event,
            compaction_event=compaction_event,
        )

    def get_capsule(self, capsule_id: str) -> StoredContextCapsule | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT artifact_id, session_id, payload, payload_sha256, event_id
                FROM context_capsule_artifacts WHERE capsule_id = ?
                """,
                (capsule_id,),
            ).fetchone()
            if row is None:
                return None
            self._validate_payload_integrity(row["payload"], row["payload_sha256"])
            event = self._event_for_id(connection, row["event_id"])
        return StoredContextCapsule(
            artifact_id=ArtifactId(UUID(row["artifact_id"])),
            session_id=SessionId(UUID(row["session_id"])),
            capsule=ContextCapsule.model_validate_json(row["payload"]),
            payload_sha256=row["payload_sha256"],
            event=event,
        )

    def get_active_capsule(self, session_id: SessionId) -> StoredContextCapsule | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT capsule_id FROM active_context_projections WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
        return None if row is None else self.get_capsule(row["capsule_id"])

    def activate_capsule(
        self,
        *,
        session_id: SessionId,
        capsule_id: str,
        expected_active_capsule_id: str | None,
        event: SessionEvent,
    ) -> StoredContextCapsule:
        if event.session_id != session_id:
            raise ValueError("activation event session does not match capsule")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT artifact_id, session_id, payload, payload_sha256,
                       source_hash, event_id
                FROM context_capsule_artifacts WHERE capsule_id = ?
                """,
                (capsule_id,),
            ).fetchone()
            if row is None or row["session_id"] != str(session_id):
                raise KeyError("context capsule is unavailable for this session")
            active_row = connection.execute(
                "SELECT capsule_id FROM active_context_projections WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
            active_id = active_row["capsule_id"] if active_row is not None else None
            if active_id != expected_active_capsule_id:
                raise ActiveContextProjectionConflictError(
                    f"active capsule changed from {expected_active_capsule_id!r} to {active_id!r}"
                )
            self._insert_event(connection, event)
            connection.execute(
                """
                UPDATE active_context_projections
                SET capsule_id = ?, artifact_id = ?, source_hash = ?,
                    event_sequence = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    capsule_id,
                    row["artifact_id"],
                    row["source_hash"],
                    event.sequence,
                    event.created_at.astimezone(UTC).isoformat(),
                    str(session_id),
                ),
            )
            created_event = self._event_for_id(connection, row["event_id"])
        return StoredContextCapsule(
            artifact_id=ArtifactId(UUID(row["artifact_id"])),
            session_id=session_id,
            capsule=ContextCapsule.model_validate_json(row["payload"]),
            payload_sha256=row["payload_sha256"],
            event=created_event,
            compaction_event=event,
        )

    @staticmethod
    def _insert_event(connection: Connection, event: SessionEvent) -> None:
        connection.execute(
            """
            INSERT INTO session_events (
                event_id, session_id, sequence, event_type, payload, actor,
                created_at, causation_id, correlation_id, idempotency_key,
                policy_version, model_profile
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.event_id),
                str(event.session_id),
                event.sequence,
                event.event_type.value,
                serialize_event_payload(event.payload),
                event.actor.value,
                event.created_at.isoformat(),
                str(event.causation_id) if event.causation_id else None,
                str(event.correlation_id) if event.correlation_id else None,
                event.idempotency_key,
                event.policy_version,
                event.model_profile,
            ),
        )

    @staticmethod
    def _event_for_id(connection: Connection, event_id: str) -> SessionEvent:
        from agent_storage.event_rows import deserialize_event_row

        row = connection.execute(
            "SELECT * FROM session_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("context capsule event is missing")
        return deserialize_event_row(row)

    @staticmethod
    def _validate_payload_integrity(payload: bytes, expected_sha256: str) -> None:
        if sha256(payload).hexdigest() != expected_sha256:
            raise ValueError("context capsule artifact failed integrity validation")

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_events (
                    event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
                    payload TEXT NOT NULL, actor TEXT NOT NULL,
                    created_at TEXT NOT NULL, causation_id TEXT,
                    correlation_id TEXT, idempotency_key TEXT,
                    policy_version TEXT, model_profile TEXT,
                    UNIQUE (session_id, sequence)
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_session_events_idempotency
                ON session_events(session_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS context_capsule_artifacts (
                    capsule_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS active_context_projections (
                    session_id TEXT PRIMARY KEY,
                    capsule_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
