from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_core.domain.tool_profiles import ToolProfile
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
                    tool_profile,
                    last_attempt_number,
                    runtime_name,
                    snapshot_id,
                    snapshot_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    workspace_root = excluded.workspace_root,
                    prepared_at = excluded.prepared_at,
                    updated_at = excluded.updated_at,
                    current_sequence = excluded.current_sequence,
                    status = excluded.status,
                    policy_profile = excluded.policy_profile,
                    tool_profile = excluded.tool_profile,
                    last_attempt_number = excluded.last_attempt_number,
                    runtime_name = excluded.runtime_name,
                    snapshot_id = excluded.snapshot_id,
                    snapshot_path = excluded.snapshot_path
                """,
                (
                    str(workspace.session_id),
                    workspace.workspace_root,
                    workspace.prepared_at.isoformat(),
                    workspace.updated_at.isoformat(),
                    workspace.current_sequence,
                    workspace.status.value,
                    workspace.policy_profile,
                    workspace.tool_profile.value,
                    workspace.last_attempt_number,
                    workspace.runtime_name,
                    workspace.snapshot_id,
                    workspace.snapshot_path,
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
                    tool_profile,
                    last_attempt_number,
                    runtime_name,
                    snapshot_id,
                    snapshot_path
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
                "tool_profile": ToolProfile(row["tool_profile"]),
                "last_attempt_number": row["last_attempt_number"],
                "runtime_name": row["runtime_name"],
                "snapshot_id": row["snapshot_id"],
                "snapshot_path": row["snapshot_path"],
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
                    tool_profile TEXT NOT NULL DEFAULT 'coding',
                    last_attempt_number INTEGER,
                    runtime_name TEXT,
                    snapshot_id TEXT,
                    snapshot_path TEXT
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(workspace_projections)"
                ).fetchall()
            }
            if "runtime_name" not in columns:
                connection.execute(
                    """
                    ALTER TABLE workspace_projections
                    ADD COLUMN runtime_name TEXT
                    """
                )
            if "tool_profile" not in columns:
                connection.execute(
                    "ALTER TABLE workspace_projections "
                    "ADD COLUMN tool_profile TEXT NOT NULL DEFAULT 'coding'"
                )
            if "snapshot_id" not in columns:
                connection.execute(
                    """
                    ALTER TABLE workspace_projections
                    ADD COLUMN snapshot_id TEXT
                    """
                )
            if "snapshot_path" not in columns:
                connection.execute(
                    """
                    ALTER TABLE workspace_projections
                    ADD COLUMN snapshot_path TEXT
                    """
                )
