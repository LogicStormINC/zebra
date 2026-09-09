"""PostgreSQL Event Store with transactional stream-version CAS."""

from typing import Any

from agent_core.contracts import SessionCommandAcceptedPayload, SessionCommandKind
from agent_core.domain.events import SessionEvent
from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.identifiers import EventId, SessionId
from agent_core.ports.event_store import EventStorePort
from psycopg import errors
from psycopg.types.json import Jsonb

from agent_storage.event_rows import (
    SessionEventSequenceConflictError,
    ensure_idempotent_event_retry,
)
from agent_storage.postgres.command_wakeup import record_command_wakeup_in_transaction
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.extension_snapshots import (
    load_extension_snapshot_in_transaction,
    resolve_extension_task_ceiling_in_transaction,
    save_extension_snapshot_in_transaction,
)
from agent_storage.postgres.extensions import (
    ExtensionSnapshotAdmissionConflictError,
    validate_skill_snapshot_in_transaction,
)


class PostgresEventStore(EventStorePort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(
            dsn,
            deployment_namespace=deployment_namespace,
        )

    def append(self, event: SessionEvent) -> SessionEvent:
        try:
            with self._database.connect() as connection:
                return append_event_in_transaction(
                    connection,
                    self._database.deployment_namespace,
                    event,
                )
        except errors.UniqueViolation as exc:
            existing = self._find_existing_after_rollback(event)
            if existing is not None:
                return ensure_idempotent_event_retry(existing, event)
            raise ValueError("duplicate or conflicting session event") from exc

    def append_with_extension_snapshot(
        self,
        event: SessionEvent,
        *,
        scope: ExtensionScope,
        snapshot: ExtensionSnapshot,
        task_ceiling: ExtensionTaskCeiling,
    ) -> SessionEvent:
        """Atomically admit one execution command and its immutable Turn inputs."""
        accepted = SessionCommandAcceptedPayload.model_validate(event.payload)
        if (
            accepted.kind
            not in {
                SessionCommandKind.MESSAGE,
                SessionCommandKind.RUN,
                SessionCommandKind.RESUME,
            }
            or str(event.session_id) != snapshot.session_id
            or accepted.extension_turn_id != snapshot.turn_id
            or accepted.extension_snapshot_digest != snapshot.digest
            or snapshot.scope != scope
            or task_ceiling.task_id != task_ceiling.binding.task_id
        ):
            raise ValueError("extension snapshot does not match execution command binding")
        try:
            with self._database.connect() as connection:
                current_ceiling = resolve_extension_task_ceiling_in_transaction(
                    connection,
                    self._database.deployment_namespace,
                    snapshot.session_id,
                )
                if current_ceiling != task_ceiling:
                    raise ExtensionSnapshotAdmissionConflictError(
                        "Task extension authority changed during admission"
                    )
                if any(
                    skill.version.skill_id not in task_ceiling.skill_components
                    for skill in snapshot.skills
                ):
                    raise ExtensionSnapshotAdmissionConflictError(
                        "selected Skill exceeds the Task ceiling"
                    )
                existing_snapshot = load_extension_snapshot_in_transaction(
                    connection,
                    self._database.deployment_namespace,
                    scope=scope,
                    session_id=snapshot.session_id,
                    turn_id=snapshot.turn_id,
                    expected_digest=snapshot.digest,
                )
                if existing_snapshot is None:
                    validate_skill_snapshot_in_transaction(
                        connection,
                        self._database.deployment_namespace,
                        scope,
                        snapshot.skills,
                    )
                canonical = append_event_in_transaction(
                    connection, self._database.deployment_namespace, event
                )
                save_extension_snapshot_in_transaction(
                    connection,
                    self._database.deployment_namespace,
                    scope,
                    snapshot,
                )
                return canonical
        except errors.UniqueViolation as exc:
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
        return _advance_stream(connection, self._database.deployment_namespace, event)

    def _find_existing_after_rollback(self, event: SessionEvent) -> SessionEvent | None:
        with self._database.connect() as connection:
            existing = self._find_existing_idempotent_event(connection, event)
            if existing is None:
                return None
            canonical = ensure_idempotent_event_retry(existing, event)
            return _record_command_wakeup(
                connection, self._database.deployment_namespace, canonical
            )

    def _find_existing_idempotent_event(
        self,
        connection: Any,
        event: SessionEvent,
    ) -> SessionEvent | None:
        return _find_idempotent_event(
            connection,
            self._database.deployment_namespace,
            event,
        )


def _event_from_row(row: dict[str, Any]) -> SessionEvent:
    return SessionEvent.model_validate(row)


def read_event_in_transaction(
    connection: Any,
    deployment_namespace: str,
    event_id: EventId,
) -> SessionEvent | None:
    row = connection.execute(
        """
        SELECT event_id, session_id, sequence, event_type, payload, actor,
               created_at, causation_id, correlation_id, idempotency_key,
               policy_version, model_profile
        FROM session_events
        WHERE deployment_namespace = %s AND event_id = %s
        """,
        (deployment_namespace, event_id),
    ).fetchone()
    return None if row is None else _event_from_row(row)


def append_event_in_transaction(
    connection: Any,
    deployment_namespace: str,
    event: SessionEvent,
) -> SessionEvent:
    """Append one Event using the caller's PostgreSQL transaction."""
    existing = _find_idempotent_event(connection, deployment_namespace, event)
    if existing is not None:
        return _record_command_wakeup(
            connection, deployment_namespace, ensure_idempotent_event_retry(existing, event)
        )
    if not _advance_stream(connection, deployment_namespace, event):
        existing = _find_idempotent_event(connection, deployment_namespace, event)
        if existing is not None:
            return _record_command_wakeup(
                connection, deployment_namespace, ensure_idempotent_event_retry(existing, event)
            )
        # A replayed event id fails the stream CAS exactly like a lost
        # race; classify by identity first: only a DIFFERENT event taking
        # the sequence is the retriable CAS loss, an id replay fails
        # closed.
        if read_event_in_transaction(connection, deployment_namespace, event.event_id) is not None:
            raise ValueError("session event id replayed with a conflicting payload")
        raise SessionEventSequenceConflictError("session event sequence already taken")
    connection.execute(
        """
        INSERT INTO session_events (
            deployment_namespace, event_id, session_id, sequence,
            event_type, payload, actor, created_at, causation_id,
            correlation_id, idempotency_key, policy_version, model_profile
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            deployment_namespace,
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
    return _record_command_wakeup(connection, deployment_namespace, event, is_new_admission=True)


def _record_command_wakeup(
    connection: Any,
    deployment_namespace: str,
    canonical: SessionEvent,
    *,
    is_new_admission: bool = False,
) -> SessionEvent:
    record_command_wakeup_in_transaction(
        connection, deployment_namespace, canonical, is_new_admission=is_new_admission
    )
    return canonical


def _advance_stream(
    connection: Any,
    deployment_namespace: str,
    event: SessionEvent,
) -> bool:
    if event.sequence == 0:
        cursor = connection.execute(
            """
            INSERT INTO session_streams (deployment_namespace, session_id, current_version)
            VALUES (%s, %s, 0)
            ON CONFLICT DO NOTHING
            RETURNING current_version
            """,
            (deployment_namespace, event.session_id),
        )
    else:
        cursor = connection.execute(
            """
            UPDATE session_streams SET current_version = %s
            WHERE deployment_namespace = %s AND session_id = %s
              AND current_version = %s
            RETURNING current_version
            """,
            (event.sequence, deployment_namespace, event.session_id, event.sequence - 1),
        )
    return cursor.fetchone() is not None


def _find_idempotent_event(
    connection: Any,
    deployment_namespace: str,
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
        WHERE deployment_namespace = %s AND session_id = %s AND idempotency_key = %s
        """,
        (deployment_namespace, event.session_id, event.idempotency_key),
    ).fetchone()
    return _event_from_row(row) if row is not None else None
