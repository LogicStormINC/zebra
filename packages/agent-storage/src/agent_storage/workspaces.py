import json
import sqlite3
from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_core.ports.workspace_projection_store import WorkspaceProjectionStorePort

from agent_storage.database import SQLiteDatabase, ensure_column


class SQLiteWorkspaceProjectionStore(WorkspaceProjectionStorePort):
    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def save_workspace(self, workspace: WorkspaceProjection) -> WorkspaceProjection:
        with self._database.connect() as connection:
            _save_workspace(connection, workspace)
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
                    network_profile,
                    network_allowlist,
                    mcp_allowlist,
                    preapproved_readonly_tools,
                    skill_components,
                    skill_component_identities,
                    agent_definition,
                    last_attempt_number,
                    runtime_name,
                    runtime_engine,
                    runtime_image,
                    runtime_spec_digest,
                    runtime_network_enforcement,
                    runtime_workspace_writable,
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
                "network_profile": NetworkProfileName(row["network_profile"]),
                "network_allowlist": tuple(json.loads(row["network_allowlist"])),
                "mcp_allowlist": (
                    None
                    if row["mcp_allowlist"] is None
                    else tuple(json.loads(row["mcp_allowlist"]))
                ),
                "preapproved_readonly_tools": (
                    None
                    if row["preapproved_readonly_tools"] is None
                    else tuple(json.loads(row["preapproved_readonly_tools"]))
                ),
                "skill_components": (
                    None
                    if row["skill_components"] is None
                    else tuple(json.loads(row["skill_components"]))
                ),
                "skill_component_identities": (
                    None
                    if row["skill_component_identities"] is None
                    else tuple(json.loads(row["skill_component_identities"]))
                ),
                "agent_definition": (
                    None
                    if row["agent_definition"] is None
                    else json.loads(row["agent_definition"])
                ),
                "last_attempt_number": row["last_attempt_number"],
                "runtime_name": row["runtime_name"],
                "runtime_engine": row["runtime_engine"],
                "runtime_image": row["runtime_image"],
                "runtime_spec_digest": row["runtime_spec_digest"],
                "runtime_network_enforcement": row["runtime_network_enforcement"],
                "runtime_workspace_writable": (
                    None
                    if row["runtime_workspace_writable"] is None
                    else bool(row["runtime_workspace_writable"])
                ),
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
                    network_profile TEXT NOT NULL DEFAULT 'none',
                    network_allowlist TEXT NOT NULL DEFAULT '[]',
                    mcp_allowlist TEXT,
                    preapproved_readonly_tools TEXT,
                    skill_components TEXT,
                    skill_component_identities TEXT,
                    agent_definition TEXT,
                    last_attempt_number INTEGER,
                    runtime_name TEXT,
                    runtime_engine TEXT,
                    runtime_image TEXT,
                    runtime_spec_digest TEXT,
                    runtime_network_enforcement TEXT,
                    runtime_workspace_writable INTEGER,
                    snapshot_id TEXT,
                    snapshot_path TEXT
                )
                """
            )
            ensure_column(connection, "workspace_projections", "runtime_name", "TEXT")
            for name, definition in (
                ("runtime_engine", "TEXT"),
                ("runtime_image", "TEXT"),
                ("runtime_spec_digest", "TEXT"),
                ("runtime_network_enforcement", "TEXT"),
                ("runtime_workspace_writable", "INTEGER"),
            ):
                ensure_column(connection, "workspace_projections", name, definition)
            ensure_column(
                connection,
                "workspace_projections",
                "tool_profile",
                "TEXT NOT NULL DEFAULT 'coding'",
            )
            ensure_column(
                connection,
                "workspace_projections",
                "network_profile",
                "TEXT NOT NULL DEFAULT 'none'",
            )
            ensure_column(
                connection,
                "workspace_projections",
                "network_allowlist",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            ensure_column(connection, "workspace_projections", "mcp_allowlist", "TEXT")
            ensure_column(
                connection,
                "workspace_projections",
                "preapproved_readonly_tools",
                "TEXT",
            )
            ensure_column(connection, "workspace_projections", "skill_components", "TEXT")
            ensure_column(
                connection,
                "workspace_projections",
                "skill_component_identities",
                "TEXT",
            )
            ensure_column(connection, "workspace_projections", "agent_definition", "TEXT")
            ensure_column(connection, "workspace_projections", "snapshot_id", "TEXT")
            ensure_column(connection, "workspace_projections", "snapshot_path", "TEXT")


def _save_workspace(
    connection: sqlite3.Connection, workspace: WorkspaceProjection
) -> None:
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
            network_profile,
            network_allowlist,
            mcp_allowlist,
            preapproved_readonly_tools,
            skill_components,
            skill_component_identities,
            agent_definition,
            last_attempt_number,
            runtime_name,
            runtime_engine,
            runtime_image,
            runtime_spec_digest,
            runtime_network_enforcement,
            runtime_workspace_writable,
            snapshot_id,
            snapshot_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            workspace_root = excluded.workspace_root,
            prepared_at = excluded.prepared_at,
            updated_at = excluded.updated_at,
            current_sequence = excluded.current_sequence,
            status = excluded.status,
            policy_profile = excluded.policy_profile,
            tool_profile = excluded.tool_profile,
            network_profile = excluded.network_profile,
            network_allowlist = excluded.network_allowlist,
            mcp_allowlist = excluded.mcp_allowlist,
            preapproved_readonly_tools = excluded.preapproved_readonly_tools,
            skill_components = excluded.skill_components,
            skill_component_identities = excluded.skill_component_identities,
            agent_definition = excluded.agent_definition,
            last_attempt_number = excluded.last_attempt_number,
            runtime_name = excluded.runtime_name,
            runtime_engine = excluded.runtime_engine,
            runtime_image = excluded.runtime_image,
            runtime_spec_digest = excluded.runtime_spec_digest,
            runtime_network_enforcement = excluded.runtime_network_enforcement,
            runtime_workspace_writable = excluded.runtime_workspace_writable,
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
            workspace.network_profile.value,
            json.dumps(workspace.network_allowlist),
            None if workspace.mcp_allowlist is None else json.dumps(workspace.mcp_allowlist),
            (
                None
                if workspace.preapproved_readonly_tools is None
                else json.dumps(workspace.preapproved_readonly_tools)
            ),
            None if workspace.skill_components is None else json.dumps(workspace.skill_components),
            (
                None
                if workspace.skill_component_identities is None
                else json.dumps(
                    [
                        identity.model_dump(mode="json")
                        for identity in workspace.skill_component_identities
                    ]
                )
            ),
            (
                None
                if workspace.agent_definition is None
                else json.dumps(workspace.agent_definition.model_dump(mode="json"))
            ),
            workspace.last_attempt_number,
            workspace.runtime_name,
            workspace.runtime_engine,
            workspace.runtime_image,
            workspace.runtime_spec_digest,
            workspace.runtime_network_enforcement,
            workspace.runtime_workspace_writable,
            workspace.snapshot_id,
            workspace.snapshot_path,
        ),
    )
