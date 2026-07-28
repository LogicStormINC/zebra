"""PostgreSQL Session Projection Store with version-aware upserts."""

from typing import Any

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports.projection_store import ProjectionStorePort
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase


class PostgresProjectionConflictError(ValueError):
    """Raised when a Projection write is stale or changes an applied version."""


class PostgresProjectionStore(ProjectionStorePort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(
            dsn,
            deployment_namespace=deployment_namespace,
        )

    def save_session(self, session: Session) -> Session:
        values = _session_values(self._database.deployment_namespace, session)
        with self._database.connect() as connection:
            stream_row = connection.execute(
                """
                SELECT current_version
                FROM session_streams
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (self._database.deployment_namespace, session.session_id),
            ).fetchone()
            if stream_row is None or stream_row["current_version"] < session.current_sequence:
                raise PostgresProjectionConflictError(
                    "session projection is ahead of its authoritative event stream"
                )
            row = connection.execute(
                """
                INSERT INTO session_projections (
                    deployment_namespace, session_id, title, status, created_at,
                    updated_at, current_sequence, approval_context_json,
                    clarification_context_json, task_plan_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, session_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    current_sequence = EXCLUDED.current_sequence,
                    approval_context_json = EXCLUDED.approval_context_json,
                    clarification_context_json = EXCLUDED.clarification_context_json,
                    task_plan_json = EXCLUDED.task_plan_json
                WHERE session_projections.current_sequence < EXCLUDED.current_sequence
                RETURNING session_id, title, status, created_at, updated_at,
                          current_sequence, approval_context_json,
                          clarification_context_json, task_plan_json
                """,
                values,
            ).fetchone()
            if row is not None:
                return _session_from_row(row)
            stored = self._get_session(connection, session.session_id)
            if stored == session:
                return stored
            if stored is None:
                raise PostgresProjectionConflictError("projection save produced no stored row")
            if stored.current_sequence > session.current_sequence:
                raise PostgresProjectionConflictError("stale session projection")
            raise PostgresProjectionConflictError(
                "session projection content conflicts at the same sequence"
            )

    def get_session(self, session_id: SessionId) -> Session | None:
        with self._database.connect() as connection:
            return self._get_session(connection, session_id)

    def list_recent_sessions(self, *, limit: int) -> list[Session]:
        if limit <= 0:
            return []
        return self._list_sessions(
            "ORDER BY updated_at DESC, created_at DESC, session_id ASC LIMIT %s",
            (limit,),
        )

    def list_ready_sessions(self, *, limit: int) -> list[Session]:
        if limit <= 0:
            return []
        return self._list_sessions(
            "AND status = %s ORDER BY updated_at ASC, created_at ASC, session_id ASC LIMIT %s",
            (SessionStatus.READY.value, limit),
        )

    def list_waiting_approval_sessions(self) -> list[Session]:
        return self._list_sessions(
            "AND status = %s ORDER BY updated_at ASC, created_at ASC, session_id ASC",
            (SessionStatus.WAITING_APPROVAL.value,),
        )

    def _get_session(self, connection: Any, session_id: SessionId) -> Session | None:
        row = connection.execute(
            f"{_SELECT_SESSION} WHERE deployment_namespace = %s AND session_id = %s",
            (self._database.deployment_namespace, session_id),
        ).fetchone()
        return _session_from_row(row) if row is not None else None

    def _list_sessions(self, clause: str, parameters: tuple[object, ...]) -> list[Session]:
        with self._database.connect() as connection:
            rows = connection.execute(
                f"{_SELECT_SESSION} WHERE deployment_namespace = %s {clause}",
                (self._database.deployment_namespace, *parameters),
            ).fetchall()
        return [_session_from_row(row) for row in rows]


_SELECT_SESSION = """
SELECT session_id, title, status, created_at, updated_at, current_sequence,
       approval_context_json, clarification_context_json, task_plan_json
FROM session_projections
"""


def _session_values(namespace: str, session: Session) -> tuple[object, ...]:
    return (
        namespace,
        session.session_id,
        session.title,
        session.status.value,
        session.created_at,
        session.updated_at,
        session.current_sequence,
        Jsonb(session.approval_context.model_dump(mode="json"))
        if session.approval_context
        else None,
        Jsonb(session.clarification_context.model_dump(mode="json"))
        if session.clarification_context
        else None,
        Jsonb(session.task_plan.model_dump(mode="json")) if session.task_plan else None,
    )


def _session_from_row(row: dict[str, Any]) -> Session:
    values = dict(row)
    values["approval_context"] = values.pop("approval_context_json")
    values["clarification_context"] = values.pop("clarification_context_json")
    values["task_plan"] = values.pop("task_plan_json")
    return Session.model_validate(values)
