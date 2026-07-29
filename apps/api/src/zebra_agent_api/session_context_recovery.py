from agent_core.domain.events import SessionEvent
from agent_core.domain.sessions import Session
from agent_core.ports import AdministrativeMutationCAS, ContextLifecycleCommitResult
from agent_storage import ControlPlaneStores


def commit_administrative_recovery(
    *,
    stores: ControlPlaneStores,
    deployment_namespace: str,
    session: Session,
    capsule_id: str,
    event: SessionEvent,
) -> ContextLifecycleCommitResult:
    """Commit one historical-capsule activation through the cloud aggregate."""
    workspace = stores.workspaces.get_workspace(session.session_id)
    if workspace is None:
        raise ValueError("context recovery requires an existing Workspace projection")
    active = stores.context_lifecycle.get_active_capsule(session.session_id)
    if active is None:
        raise ValueError("context recovery requires an active Context capsule")
    return stores.context_lifecycle.commit_administrative_activation(
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
