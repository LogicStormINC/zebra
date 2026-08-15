import sqlite3
from pathlib import Path

from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.event_store import EventStorePort

from agent_storage.database import SQLiteDatabase
from agent_storage.event_rows import deserialize_event_row, serialize_event_payload
from agent_storage.projections import _save_session
from agent_storage.workspaces import _save_workspace


class SQLiteEventStore(EventStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def append(self, event: SessionEvent) -> SessionEvent:
        with self._database.connect() as connection:
            try:
                _insert_event(connection, event)
            except sqlite3.IntegrityError as exc:
                existing_event = self._find_existing_idempotent_event(connection, event)
                if existing_event is not None:
                    return existing_event
                raise ValueError("duplicate or conflicting session event") from exc
        return event

    def append_completed_and_release_lease(
        self,
        event: SessionEvent,
        *,
        session: Session,
        workspace: WorkspaceProjection,
        worker_id: str,
    ) -> None:
        if event.event_type is not EventType.SESSION_COMPLETED:
            raise ValueError("atomic worker finalization requires session_completed")
        if event.session_id != session.session_id or event.session_id != workspace.session_id:
            raise ValueError("atomic worker finalization session_id does not match")
        if event.sequence != session.current_sequence + 1:
            raise ValueError("atomic worker finalization sequence does not match")
        completed_session = apply_event(session, event)
        completed_workspace = apply_workspace_event(workspace, event)
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _insert_event(connection, event)
            _save_session(connection, completed_session)
            _save_workspace(connection, completed_workspace)
            released = connection.execute(
                "DELETE FROM worker_leases WHERE session_id = ? AND worker_id = ?",
                (str(event.session_id), worker_id),
            )
            if released.rowcount != 1:
                raise ValueError("worker lease is no longer owned by worker")

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


def _insert_event(connection: sqlite3.Connection, event: SessionEvent) -> None:
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
