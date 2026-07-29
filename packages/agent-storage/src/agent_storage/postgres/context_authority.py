"""Projection guards shared by administrative Context transactions."""

from typing import Any

from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports import AdministrativeMutationCAS

from agent_storage.postgres.projections import get_session_in_transaction
from agent_storage.postgres.workspaces import get_workspace_in_transaction


class PostgresContextLifecycleConflictError(ValueError):
    """Raised when immutable Context state or administrative CAS conflicts."""


def require_administrative_projections(
    connection: Any,
    deployment_namespace: str,
    *,
    authority: AdministrativeMutationCAS,
    session: Session,
    workspace: WorkspaceProjection,
) -> None:
    """Lock the stream and reject missing, stale, or altered projections."""
    stream = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s
        FOR UPDATE
        """,
        (deployment_namespace, authority.session_id),
    ).fetchone()
    if stream is None or stream["current_version"] != authority.expected_stream_revision:
        raise PostgresContextLifecycleConflictError(
            "administrative Context stream revision changed"
        )
    current_session = get_session_in_transaction(
        connection, deployment_namespace, authority.session_id
    )
    current_workspace = get_workspace_in_transaction(
        connection, deployment_namespace, authority.session_id
    )
    if (
        current_session is None
        or current_workspace is None
        or current_session.current_sequence != authority.expected_stream_revision
        or current_workspace.current_sequence != authority.expected_stream_revision
        or current_session != session
        or current_workspace != workspace
    ):
        raise PostgresContextLifecycleConflictError(
            "administrative Context projections changed"
        )
