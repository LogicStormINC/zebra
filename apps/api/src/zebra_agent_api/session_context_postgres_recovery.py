from agent_core.domain.events import SessionEvent
from agent_core.domain.sessions import Session
from agent_core.ports import (
    AdministrativeMutationCAS,
    ContextLifecycleCommitResult,
    StoredContextCapsule,
)
from agent_storage import (
    ControlPlaneStores,
    PostgresContextLifecycleConflictError,
    PostgresContextLifecycleStore,
)

from zebra_agent_api.responses import ApiResponse, conflict


def commit_postgres_context_recovery(
    *,
    stores: ControlPlaneStores,
    lifecycle: PostgresContextLifecycleStore,
    deployment_namespace: str,
    session_id: str,
    session: Session,
    active: StoredContextCapsule | None,
    capsule_id: str,
    event: SessionEvent,
) -> ContextLifecycleCommitResult | ApiResponse:
    if active is None:
        return conflict(
            session_id=session_id,
            status="context_pointer_missing",
            reason="historical recovery requires an active Context pointer",
        )
    workspace = stores.workspaces.get_workspace(session.session_id)
    if workspace is None:
        return conflict(
            session_id=session_id,
            status="context_workspace_missing",
            reason="historical recovery requires a current Workspace projection",
        )
    try:
        return lifecycle.commit_administrative_activation(
            authority=AdministrativeMutationCAS(
                deployment_namespace=deployment_namespace,
                session_id=session.session_id,
                expected_stream_revision=session.current_sequence,
            ),
            session=session,
            workspace=workspace,
            capsule_id=capsule_id,
            expected_active_capsule_id=active.capsule.capsule_id,
            event=event,
        )
    except (PostgresContextLifecycleConflictError, ValueError) as exc:
        return conflict(
            session_id=session_id,
            status="context_recovery_conflict",
            reason=str(exc),
        )
