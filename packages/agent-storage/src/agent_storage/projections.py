import json
from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_core.ports.projection_store import ProjectionStorePort

from agent_storage.database import SQLiteDatabase


class SQLiteProjectionStore(ProjectionStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def save_session(self, session: Session) -> Session:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO session_projections (
                    session_id,
                    title,
                    status,
                    created_at,
                    updated_at,
                    current_sequence,
                    approval_context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    current_sequence = excluded.current_sequence,
                    approval_context_json = excluded.approval_context_json
                """,
                (
                    str(session.session_id),
                    session.title,
                    session.status.value,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.current_sequence,
                    _approval_context_json(session.approval_context),
                ),
            )
        return session

    def get_session(self, session_id: SessionId) -> Session | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    title,
                    status,
                    created_at,
                    updated_at,
                    current_sequence,
                    approval_context_json
                FROM session_projections
                WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()
        if row is None:
            return None
        return Session.model_validate(
            {
                "session_id": row["session_id"],
                "title": row["title"],
                "status": SessionStatus(row["status"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "current_sequence": row["current_sequence"],
                "approval_context": _approval_context_from_json(
                    row["approval_context_json"]
                ),
            }
        )

    def list_ready_sessions(self, *, limit: int) -> list[Session]:
        if limit <= 0:
            return []
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    title,
                    status,
                    created_at,
                    updated_at,
                    current_sequence,
                    approval_context_json
                FROM session_projections
                WHERE status = ?
                ORDER BY updated_at ASC, created_at ASC, session_id ASC
                LIMIT ?
                """,
                (SessionStatus.READY.value, limit),
            ).fetchall()
        return [
            Session.model_validate(
                {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "status": SessionStatus(row["status"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "current_sequence": row["current_sequence"],
                    "approval_context": _approval_context_from_json(
                        row["approval_context_json"]
                    ),
                }
            )
            for row in rows
        ]

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_projections (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    current_sequence INTEGER NOT NULL,
                    approval_context_json TEXT
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(session_projections)"
                ).fetchall()
            }
            if "approval_context_json" not in columns:
                connection.execute(
                    """
                    ALTER TABLE session_projections
                    ADD COLUMN approval_context_json TEXT
                    """
                )


def _approval_context_json(context: ApprovalContext | None) -> str | None:
    if context is None:
        return None
    return json.dumps(context.model_dump(mode="json"))


def _approval_context_from_json(value: object) -> ApprovalContext | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return ApprovalContext.model_validate(json.loads(value))
