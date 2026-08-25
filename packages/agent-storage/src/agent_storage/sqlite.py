import sqlite3
from pathlib import Path

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.event_store import EventStorePort

from agent_storage.database import SQLiteDatabase
from agent_storage.event_rows import (
    SessionEventSequenceConflictError,
    deserialize_event_row,
    ensure_idempotent_event_retry,
    serialize_event_payload,
)


class SQLiteEventStore(EventStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def append(self, event: SessionEvent) -> SessionEvent:
        with self._database.connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO session_events (
                        event_id,
                        session_id,
                        sequence,
                        event_type,
                        payload,
                        actor,
                        created_at,
                        causation_id,
                        correlation_id,
                        idempotency_key,
                        policy_version,
                        model_profile
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
            except sqlite3.IntegrityError as exc:
                existing_event = self._find_existing_idempotent_event(connection, event)
                if existing_event is not None:
                    return ensure_idempotent_event_retry(existing_event, event)
                taken = connection.execute(
                    """
                    SELECT 1 FROM session_events
                    WHERE session_id = ? AND sequence = ?
                    """,
                    (str(event.session_id), event.sequence),
                ).fetchone()
                if taken is not None:
                    # The sequence is genuinely taken: the lost CAS race.
                    raise SessionEventSequenceConflictError(
                        "session event sequence already taken"
                    ) from exc
                raise ValueError("duplicate or conflicting session event") from exc
        return event

    def list_for_session(self, session_id: SessionId) -> list[SessionEvent]:
        return self.read_since(session_id, sequence=-1)

    def read_since(self, session_id: SessionId, sequence: int) -> list[SessionEvent]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    session_id,
                    sequence,
                    event_type,
                    payload,
                    actor,
                    created_at,
                    causation_id,
                    correlation_id,
                    idempotency_key,
                    policy_version,
                    model_profile
                FROM session_events
                WHERE session_id = ?
                  AND sequence > ?
                ORDER BY sequence ASC
                """,
                (str(session_id), sequence),
            ).fetchall()
        return [deserialize_event_row(row) for row in rows]

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    causation_id TEXT,
                    correlation_id TEXT,
                    idempotency_key TEXT,
                    policy_version TEXT,
                    model_profile TEXT,
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

    def _find_existing_idempotent_event(
        self,
        connection: sqlite3.Connection,
        event: SessionEvent,
    ) -> SessionEvent | None:
        if event.idempotency_key is None:
            return None
        row = connection.execute(
            """
            SELECT
                event_id,
                session_id,
                sequence,
                event_type,
                payload,
                actor,
                created_at,
                causation_id,
                correlation_id,
                idempotency_key,
                policy_version,
                model_profile
            FROM session_events
            WHERE session_id = ? AND idempotency_key = ?
            """,
            (str(event.session_id), event.idempotency_key),
        ).fetchone()
        if row is None:
            return None
        return deserialize_event_row(row)
