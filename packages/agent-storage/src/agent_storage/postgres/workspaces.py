"""Fenced PostgreSQL Workspace projection writes and Event replay."""

from typing import Any

from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.application.workspace_projection import (
    rebuild_workspace,
)
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.sessions import Session
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.workspace_projection_store import (
    WorkerProjectionCommitResult,
    WorkerProjectionTransactionPort,
    WorkspaceProjectionStorePort,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.projections import (
    get_session_in_transaction,
    save_session_in_transaction,
)


class PostgresWorkspaceProjectionConflictError(ValueError):
    """Raised when a Workspace replay or projection commit is not monotonic."""


class PostgresWorkspaceProjectionStore(
    WorkspaceProjectionStorePort,
    WorkerProjectionTransactionPort,
):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def save_workspace(self, workspace: WorkspaceProjection) -> WorkspaceProjection:
        """Replay an Event-derived projection without asserting Worker ownership."""
        with self._database.connect() as connection:
            return save_workspace_in_transaction(
                connection,
                self._database.deployment_namespace,
                workspace,
            )

    def commit_worker_event(
        self,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
        *,
        authority: WorkerMutationAuthority,
    ) -> WorkerProjectionCommitResult:
        self._validate_worker_commit(event, session, workspace, authority)
        with self._database.connect() as connection:
            assert_current_lease_fence(
                connection,
                self._database.deployment_namespace,
                event.session_id,
                authority.lease_fence,
            )
            persisted_event = append_event_in_transaction(
                connection,
                self._database.deployment_namespace,
                event,
            )
            if persisted_event.sequence != authority.expected_stream_revision + 1:
                raise PostgresWorkspaceProjectionConflictError(
                    "canonical Event does not follow the expected stream revision"
                )
            canonical_session, canonical_workspace, already_projected = (
                self._resolve_canonical_projections(
                    connection,
                    persisted_event,
                    session,
                    workspace,
                )
            )
            if already_projected:
                return WorkerProjectionCommitResult(
                    event=persisted_event,
                    session=canonical_session,
                    workspace=canonical_workspace,
                )
            stored_session = save_session_in_transaction(
                connection,
                self._database.deployment_namespace,
                canonical_session,
            )
            stored_workspace = save_workspace_in_transaction(
                connection,
                self._database.deployment_namespace,
                canonical_workspace,
            )
            return WorkerProjectionCommitResult(
                event=persisted_event,
                session=stored_session,
                workspace=stored_workspace,
            )

    def get_workspace(self, session_id: SessionId) -> WorkspaceProjection | None:
        with self._database.connect() as connection:
            return get_workspace_in_transaction(
                connection,
                self._database.deployment_namespace,
                session_id,
            )

    def _validate_worker_commit(
        self,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
        authority: WorkerMutationAuthority,
    ) -> None:
        namespace = self._database.deployment_namespace
        if authority.deployment_namespace != namespace:
            raise LeaseLostError("workspace mutation authority belongs to another namespace")
        if authority.session_id != event.session_id:
            raise LeaseLostError("workspace mutation authority belongs to another session")
        if session.session_id != event.session_id or workspace.session_id != event.session_id:
            raise PostgresWorkspaceProjectionConflictError(
                "event and projections must belong to the same session"
            )

    def _resolve_canonical_projections(
        self,
        connection: Any,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
    ) -> tuple[Session, WorkspaceProjection, bool]:
        namespace = self._database.deployment_namespace
        current_session = get_session_in_transaction(connection, namespace, event.session_id)
        if current_session is None:
            raise PostgresWorkspaceProjectionConflictError(
                "worker projection commit requires an existing Session projection"
            )
        current_workspace = get_workspace_in_transaction(
            connection,
            namespace,
            event.session_id,
        )
        if current_session.current_sequence == event.sequence:
            if current_workspace is None or current_workspace.current_sequence != event.sequence:
                raise PostgresWorkspaceProjectionConflictError(
                    "canonical Worker projections are incomplete"
                )
            return current_session, current_workspace, True
        if current_session.current_sequence != event.sequence - 1:
            raise PostgresWorkspaceProjectionConflictError(
                "session projection does not precede the canonical Event"
            )
        expected_session = apply_session_event(current_session, event)
        if session != expected_session:
            raise PostgresWorkspaceProjectionConflictError(
                "session projection content is not derived from the Event"
            )
        if current_workspace is None:
            if event.event_type is not EventType.TASK_PREPARED:
                raise PostgresWorkspaceProjectionConflictError(
                    "first workspace projection requires TASK_PREPARED"
                )
            expected_workspace = rebuild_workspace([event])
        else:
            expected_workspace = apply_workspace_event(current_workspace, event)
        if workspace != expected_workspace:
            raise PostgresWorkspaceProjectionConflictError(
                "workspace projection content is not derived from the Event"
            )
        return expected_session, expected_workspace, False


def save_workspace_in_transaction(
    connection: Any,
    deployment_namespace: str,
    workspace: WorkspaceProjection,
) -> WorkspaceProjection:
    """Save one monotonic Workspace projection in the caller's transaction."""
    stream_row = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s
        FOR SHARE
        """,
        (deployment_namespace, workspace.session_id),
    ).fetchone()
    if stream_row is None or stream_row["current_version"] < workspace.current_sequence:
        raise PostgresWorkspaceProjectionConflictError(
            "workspace projection is ahead of its authoritative event stream"
        )
    row = connection.execute(
        f"""
        INSERT INTO workspace_projections ({_WORKSPACE_COLUMNS})
        VALUES ({", ".join(["%s"] * 23)})
        ON CONFLICT (deployment_namespace, session_id) DO UPDATE SET
            workspace_root = EXCLUDED.workspace_root,
            prepared_at = EXCLUDED.prepared_at,
            updated_at = EXCLUDED.updated_at,
            current_sequence = EXCLUDED.current_sequence,
            status = EXCLUDED.status,
            policy_profile = EXCLUDED.policy_profile,
            tool_profile = EXCLUDED.tool_profile,
            network_profile = EXCLUDED.network_profile,
            network_allowlist = EXCLUDED.network_allowlist,
            mcp_allowlist = EXCLUDED.mcp_allowlist,
            skill_components = EXCLUDED.skill_components,
            last_attempt_number = EXCLUDED.last_attempt_number,
            runtime_name = EXCLUDED.runtime_name,
            runtime_engine = EXCLUDED.runtime_engine,
            runtime_image = EXCLUDED.runtime_image,
            runtime_spec_digest = EXCLUDED.runtime_spec_digest,
            runtime_network_enforcement = EXCLUDED.runtime_network_enforcement,
            runtime_workspace_writable = EXCLUDED.runtime_workspace_writable,
            snapshot_id = EXCLUDED.snapshot_id,
            snapshot_path = EXCLUDED.snapshot_path,
            definition_snapshot = EXCLUDED.definition_snapshot
        WHERE workspace_projections.current_sequence < EXCLUDED.current_sequence
        RETURNING {_WORKSPACE_RETURNING_COLUMNS}
        """,
        _workspace_values(deployment_namespace, workspace),
    ).fetchone()
    if row is not None:
        return _workspace_from_row(row)
    stored = get_workspace_in_transaction(
        connection,
        deployment_namespace,
        workspace.session_id,
    )
    if stored == workspace:
        return stored
    if stored is None:
        raise PostgresWorkspaceProjectionConflictError(
            "workspace projection save produced no stored row"
        )
    if stored.current_sequence > workspace.current_sequence:
        raise PostgresWorkspaceProjectionConflictError("stale workspace projection")
    raise PostgresWorkspaceProjectionConflictError(
        "workspace projection content conflicts at the same sequence"
    )


def get_workspace_in_transaction(
    connection: Any,
    deployment_namespace: str,
    session_id: SessionId,
) -> WorkspaceProjection | None:
    row = connection.execute(
        f"""
        SELECT {_WORKSPACE_RETURNING_COLUMNS}
        FROM workspace_projections
        WHERE deployment_namespace = %s AND session_id = %s
        """,
        (deployment_namespace, session_id),
    ).fetchone()
    return None if row is None else _workspace_from_row(row)


_WORKSPACE_COLUMNS = """
deployment_namespace, session_id, workspace_root, prepared_at, updated_at,
current_sequence, status, policy_profile, tool_profile, network_profile,
network_allowlist, mcp_allowlist, skill_components, last_attempt_number,
runtime_name, runtime_engine, runtime_image, runtime_spec_digest,
runtime_network_enforcement, runtime_workspace_writable, snapshot_id, snapshot_path,
definition_snapshot
""".strip()

_WORKSPACE_RETURNING_COLUMNS = """
session_id, workspace_root, prepared_at, updated_at, current_sequence, status,
policy_profile, tool_profile, network_profile, network_allowlist, mcp_allowlist,
skill_components, last_attempt_number, runtime_name, runtime_engine, runtime_image,
runtime_spec_digest, runtime_network_enforcement, runtime_workspace_writable,
snapshot_id, snapshot_path, definition_snapshot
""".strip()


def _workspace_values(
    deployment_namespace: str,
    workspace: WorkspaceProjection,
) -> tuple[object, ...]:
    return (
        deployment_namespace,
        workspace.session_id,
        workspace.workspace_root,
        workspace.prepared_at,
        workspace.updated_at,
        workspace.current_sequence,
        workspace.status.value,
        workspace.policy_profile,
        workspace.tool_profile.value,
        workspace.network_profile.value,
        Jsonb(workspace.network_allowlist),
        None if workspace.mcp_allowlist is None else Jsonb(workspace.mcp_allowlist),
        None if workspace.skill_components is None else Jsonb(workspace.skill_components),
        workspace.last_attempt_number,
        workspace.runtime_name,
        workspace.runtime_engine,
        workspace.runtime_image,
        workspace.runtime_spec_digest,
        workspace.runtime_network_enforcement,
        workspace.runtime_workspace_writable,
        workspace.snapshot_id,
        workspace.snapshot_path,
        (
            None
            if workspace.definition_snapshot is None
            else Jsonb(
                workspace.definition_snapshot.model_dump(mode="json", exclude_none=True)
            )
        ),
    )


def _workspace_from_row(row: dict[str, Any]) -> WorkspaceProjection:
    values = dict(row)
    values["status"] = WorkspaceStatus(values["status"])
    values["tool_profile"] = ToolProfile(values["tool_profile"])
    values["network_profile"] = NetworkProfileName(values["network_profile"])
    values["network_allowlist"] = tuple(values["network_allowlist"])
    if values["mcp_allowlist"] is not None:
        values["mcp_allowlist"] = tuple(values["mcp_allowlist"])
    if values["skill_components"] is not None:
        values["skill_components"] = tuple(values["skill_components"])
    if values["definition_snapshot"] is not None:
        values["definition_snapshot"] = AgentDefinitionSnapshot.model_validate(
            values["definition_snapshot"]
        )
    return WorkspaceProjection.model_validate(values)
