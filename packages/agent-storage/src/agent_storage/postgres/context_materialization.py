"""One-transaction PostgreSQL Context input read composition."""

from typing import Any

from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationRequest,
)
from agent_core.domain.session_history import SessionHistoryMessage
from agent_core.ports.context_materialization import ContextMaterializationPort

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.governed_memory_rows import query_authority_entries
from agent_storage.postgres.session_history_rows import message_from_row

_SAFE_EVENT_TYPES = ("user_message_received", "model_response_received")


class PostgresContextMaterializationConflictError(RuntimeError):
    """The requested read generation no longer has one coherent source state."""


class PostgresContextMaterializationStore(ContextMaterializationPort):
    """Compose the three authoritative Context inputs in one read transaction."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def materialize(self, request: ContextMaterializationRequest) -> ContextMaterialization:
        with self._database.connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            session_revision = self._session_revision(connection, request)
            history = self._history(connection, request)
            capsule = self._active_capsule(connection, request)
            memories = (
                []
                if request.memory_query is None
                else query_authority_entries(
                    connection,
                    self._database.deployment_namespace,
                    request.memory_query,
                    as_of=request.as_of,
                )
            )
        return ContextMaterialization(
            request=request,
            session_revision=session_revision,
            history=history,
            active_capsule=capsule,
            memories=tuple(memories),
        )

    def _session_revision(self, connection: Any, request: ContextMaterializationRequest) -> int:
        row = connection.execute(
            """
            SELECT current_sequence
            FROM session_projections
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (self._database.deployment_namespace, request.session_id),
        ).fetchone()
        if row is None:
            raise PostgresContextMaterializationConflictError("Session projection is missing")
        revision = int(row["current_sequence"])
        if revision != request.expected_session_revision:
            raise PostgresContextMaterializationConflictError("Session revision is stale")
        return revision

    def _history(
        self, connection: Any, request: ContextMaterializationRequest
    ) -> tuple[SessionHistoryMessage, ...]:
        rows = connection.execute(
            """
            SELECT sequence, event_type, payload, created_at
            FROM session_events
            WHERE deployment_namespace = %s AND session_id = %s
              AND event_type IN (%s, %s)
            ORDER BY sequence ASC
            LIMIT %s
            """,
            (
                self._database.deployment_namespace,
                request.session_id,
                *_SAFE_EVENT_TYPES,
                request.history_limit,
            ),
        ).fetchall()
        return tuple(message for row in rows if (message := message_from_row(row)) is not None)

    def _active_capsule(
        self, connection: Any, request: ContextMaterializationRequest
    ) -> ContextCapsule | None:
        row = connection.execute(
            """
            SELECT p.capsule_id, p.source_hash, c.payload
            FROM active_context_projections AS p
            JOIN context_capsule_artifacts AS c
              ON c.deployment_namespace = p.deployment_namespace
             AND c.session_id = p.session_id
             AND c.capsule_id = p.capsule_id
             AND c.artifact_id = p.artifact_id
            WHERE p.deployment_namespace = %s AND p.session_id = %s
            """,
            (self._database.deployment_namespace, request.session_id),
        ).fetchone()
        if row is None:
            if request.expected_active_capsule_id is not None:
                raise PostgresContextMaterializationConflictError(
                    "active Context Capsule is missing"
                )
            return None
        if row["capsule_id"] != request.expected_active_capsule_id:
            raise PostgresContextMaterializationConflictError("active Context Capsule is stale")
        capsule = ContextCapsule.model_validate(row["payload"])
        if capsule.capsule_id != row["capsule_id"] or capsule.source_hash != row["source_hash"]:
            raise PostgresContextMaterializationConflictError(
                "active Context Capsule payload does not match its pointer"
            )
        return capsule
