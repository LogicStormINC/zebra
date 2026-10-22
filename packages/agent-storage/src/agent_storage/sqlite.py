import json
import sqlite3
from pathlib import Path

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import ClientSessionId, SessionId, TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.client_command_receipts import ClientCommandReceipt
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.session_recovery import SessionEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady

from agent_storage.database import SQLiteDatabase
from agent_storage.event_rows import (
    SessionEventSequenceConflictError,
    deserialize_event_row,
    ensure_idempotent_event_retry,
    serialize_event_payload,
)
from agent_storage.task_event_page_limits import admitted_page_positions, validate_page_request


class SQLiteEventStore(EventStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def read_client_command_receipt(
        self,
        segment_id: SessionId,
        key: str,
        task_id: TaskId,
        run_id: str,
        client_session_id: ClientSessionId,
    ) -> ClientCommandReceipt | None:
        from agent_storage.client_command_receipts import read_receipt

        with self._database.connect() as connection:
            return read_receipt(
                connection, (str(segment_id), key, str(task_id), run_id, str(client_session_id))
            )

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
                    SELECT event_id FROM session_events
                    WHERE session_id = ? AND sequence = ?
                    """,
                    (str(event.session_id), event.sequence),
                ).fetchone()
                if taken is None:
                    raise ValueError("duplicate or conflicting session event") from exc
                if str(taken["event_id"]) == str(event.event_id):
                    # Same event id replayed (same or different content):
                    # an identity conflict, NEVER a retriable sequence race.
                    raise ValueError(
                        "session event id replayed with a conflicting payload"
                    ) from exc
                # A DIFFERENT event already took the sequence: the lost CAS.
                raise SessionEventSequenceConflictError(
                    "session event sequence already taken"
                ) from exc
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

    def read_session_highwater(self, session_id: SessionId) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT MAX(sequence) AS highwater FROM session_events WHERE session_id=?",
                (str(session_id),),
            ).fetchone()
        if row["highwater"] is None:
            raise ValueError("canonical Session source is unavailable")
        return int(row["highwater"])

    def read_session_status(self, session_id: SessionId) -> SessionStatus:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT status,current_sequence FROM session_observation_headers "
                "WHERE deployment_namespace='' AND session_id=?",
                (str(session_id),),
            ).fetchone()
        if row is None or row["current_sequence"] != self.read_session_highwater(session_id):
            raise CheckpointNotReady("Session observation header requires explicit preparation")
        return SessionStatus(row["status"])

    def read_session_event_page(
        self,
        session_id: SessionId,
        after_sequence: int,
        *,
        through_sequence: int | None = None,
        limit: int = 256,
        max_bytes: int = 1_048_576,
    ) -> SessionEventPage:
        validate_page_request(after_sequence, limit, max_bytes, through_sequence)
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            source = connection.execute(
                "SELECT MAX(sequence) AS highwater FROM session_events WHERE session_id=?",
                (str(session_id),),
            ).fetchone()["highwater"]
            through = source if through_sequence is None else through_sequence
            if source is None or not after_sequence <= through <= source:
                raise ValueError("Session page cursor exceeds canonical source")
            if "event_bytes_bound" not in {
                row[1] for row in connection.execute("PRAGMA table_info(session_events)")
            }:
                raise CheckpointNotReady("Session Event byte bounds require explicit preparation")
            metadata = connection.execute(
                "SELECT sequence,event_bytes_bound FROM session_events "
                "WHERE session_id=? AND sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
                (str(session_id), after_sequence, through, limit),
            ).fetchall()
            if any(row["event_bytes_bound"] is None for row in metadata):
                raise CheckpointNotReady("Session Event byte bounds require explicit preparation")
            positions = admitted_page_positions(
                [(row["sequence"], row["event_bytes_bound"]) for row in metadata],
                after=after_sequence,
                highwater=through,
                max_bytes=max_bytes,
            )
            rows = (
                []
                if not positions
                else connection.execute(
                    "SELECT * FROM session_events WHERE session_id=? "
                    "AND sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
                    (str(session_id), after_sequence, positions[-1], len(positions)),
                ).fetchall()
            )
            if len(rows) != len(positions):
                raise ValueError("Session page changed during canonical read")
            events = tuple(deserialize_event_row(row) for row in rows)
            size = sum(
                len(
                    json.dumps(
                        event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
                    ).encode()
                )
                for event in events
            )
            if size > max_bytes:
                raise ValueError("Session page exceeds admitted byte budget")
            return SessionEventPage(session_id, events, after_sequence, through, size)

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
