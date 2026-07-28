"""PostgreSQL Event Store with transactional stream-version CAS."""

from typing import Any

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.event_store import EventStorePort
from psycopg import errors
from psycopg.types.json import Jsonb

from agent_storage.event_rows import ensure_idempotent_event_retry
from agent_storage.postgres.database import PostgresDatabase


class PostgresEventStore(EventStorePort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(
            dsn,
            deployment_namespace=deployment_namespace,
        )

    def append(self, event: SessionEvent) -> SessionEvent:
        try:
            with self._database.connect() as connection:
                existing = self._find_existing_idempotent_event(connection, event)
                if existing is not None:
                    return ensure_idempotent_event_retry(existing, event)
                if not self._advance_stream(connection, event):
                    existing = self._find_existing_idempotent_event(connection, event)
                    if existing is not None:
                        return ensure_idempotent_event_retry(existing, event)
                    raise ValueError("duplicate or conflicting session event")
                connection.execute(
                    """
                    INSERT INTO session_events (
                        deployment_namespace, event_id, session_id, sequence,
                        event_type, payload, actor, created_at, causation_id,
                        correlation_id, idempotency_key, policy_version, model_profile
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        self._database.deployment_namespace,
                        event.event_id,
                        event.session_id,
                        event.sequence,
                        event.event_type.value,
                        Jsonb(event.payload),
                        event.actor.value,
                        event.created_at,
                        event.causation_id,
                        event.correlation_id,
                        event.idempotency_key,
                        event.policy_version,
                        event.model_profile,
                    ),
                )
            return event
        except errors.UniqueViolation as exc:
            existing = self._find_existing_after_rollback(event)
            if existing is not None:
                return ensure_idempotent_event_retry(existing, event)
            raise ValueError("duplicate or conflicting session event") from exc

    def list_for_session(self, session_id: SessionId) -> list[SessionEvent]:
        return self.read_since(session_id, sequence=-1)

    def read_since(self, session_id: SessionId, sequence: int) -> list[SessionEvent]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, session_id, sequence, event_type, payload, actor,
                       created_at, causation_id, correlation_id, idempotency_key,
                       policy_version, model_profile
                FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s AND sequence > %s
                ORDER BY sequence ASC
                """,
                (self._database.deployment_namespace, session_id, sequence),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def _advance_stream(self, connection: Any, event: SessionEvent) -> bool:
        if event.sequence == 0:
            cursor = connection.execute(
                """
                INSERT INTO session_streams (
                    deployment_namespace, session_id, current_version
                ) VALUES (%s, %s, 0)
                ON CONFLICT DO NOTHING
                RETURNING current_version
                """,
                (self._database.deployment_namespace, event.session_id),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE session_streams
                SET current_version = %s
                WHERE deployment_namespace = %s
                  AND session_id = %s
                  AND current_version = %s
                RETURNING current_version
                """,
                (
                    event.sequence,
                    self._database.deployment_namespace,
                    event.session_id,
                    event.sequence - 1,
                ),
            )
        return cursor.fetchone() is not None

    def _find_existing_after_rollback(self, event: SessionEvent) -> SessionEvent | None:
        with self._database.connect() as connection:
            return self._find_existing_idempotent_event(connection, event)

    def _find_existing_idempotent_event(
        self,
        connection: Any,
        event: SessionEvent,
    ) -> SessionEvent | None:
        if event.idempotency_key is None:
            return None
        row = connection.execute(
            """
            SELECT event_id, session_id, sequence, event_type, payload, actor,
                   created_at, causation_id, correlation_id, idempotency_key,
                   policy_version, model_profile
            FROM session_events
            WHERE deployment_namespace = %s
              AND session_id = %s
              AND idempotency_key = %s
            """,
            (
                self._database.deployment_namespace,
                event.session_id,
                event.idempotency_key,
            ),
        ).fetchone()
        return _event_from_row(row) if row is not None else None


def _event_from_row(row: dict[str, Any]) -> SessionEvent:
    return SessionEvent.model_validate(row)
