from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session, SessionStatus
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
                    current_sequence
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    current_sequence = excluded.current_sequence
                """,
                (
                    str(session.session_id),
                    session.title,
                    session.status.value,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.current_sequence,
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
                    current_sequence
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
                    current_sequence
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
                    current_sequence INTEGER NOT NULL
                )
                """
            )
