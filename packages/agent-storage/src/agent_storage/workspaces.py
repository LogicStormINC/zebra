from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_core.ports.workspace_projection_store import WorkspaceProjectionStorePort

from agent_storage.database import SQLiteDatabase


class SQLiteWorkspaceProjectionStore(WorkspaceProjectionStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def save_workspace(self, workspace: WorkspaceProjection) -> WorkspaceProjection:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_projections (
                    session_id,
                    workspace_root,
                    prepared_at,
                    updated_at,
                    current_sequence,
                    status,
                    policy_profile,
                    last_attempt_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    workspace_root = excluded.workspace_root,
                    prepared_at = excluded.prepared_at,
                    updated_at = excluded.updated_at,
                    current_sequence = excluded.current_sequence,
                    status = excluded.status,
                    policy_profile = excluded.policy_profile,
                    last_attempt_number = excluded.last_attempt_number
                """,
                (
                    str(workspace.session_id),
                    workspace.workspace_root,
                    workspace.prepared_at.isoformat(),
                    workspace.updated_at.isoformat(),
                    workspace.current_sequence,
                    workspace.status.value,
                    workspace.policy_profile,
                    workspace.last_attempt_number,
                ),
            )
        return workspace

    def get_workspace(self, session_id: SessionId) -> WorkspaceProjection | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    workspace_root,
                    prepared_at,
                    updated_at,
                    current_sequence,
                    status,
                    policy_profile,
                    last_attempt_number
                FROM workspace_projections
                WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()
        if row is None:
            return None
        return WorkspaceProjection.model_validate(
            {
                "session_id": row["session_id"],
                "workspace_root": row["workspace_root"],
                "prepared_at": row["prepared_at"],
                "updated_at": row["updated_at"],
                "current_sequence": row["current_sequence"],
                "status": WorkspaceStatus(row["status"]),
                "policy_profile": row["policy_profile"],
                "last_attempt_number": row["last_attempt_number"],
            }
        )

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_projections (
                    session_id TEXT PRIMARY KEY,
                    workspace_root TEXT NOT NULL,
                    prepared_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    current_sequence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    policy_profile TEXT,
                    last_attempt_number INTEGER
                )
                """
            )
