"""One cumulative two-second preparation slice; only committed pages advance recovery."""

from time import monotonic

from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.projection_store import ProjectionStorePort
from agent_core.ports.session_recovery import SessionRecoveryPort
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_core.ports.worker_preparation import PreparationAdvanced
from agent_core.ports.workspace_projection_store import WorkspaceProjectionStorePort
from agent_storage.postgres.task_io import task_io_deadline
from psycopg.errors import LockNotAvailable, QueryCanceled

from zebra_agent_worker.recovery import SessionRecoveryError


class SessionRecoveryPending(CheckpointNotReady):
    """Retryable preparation yield. This is not a failed Session or an execution permit."""


def recover_cloud_session(
    session_id: SessionId,
    store: SessionRecoveryPort,
    projections: ProjectionStorePort,
    workspaces: WorkspaceProjectionStorePort | None,
    *,
    authority: WorkerMutationAuthority,
) -> tuple[Session, WorkspaceProjection, int]:
    deadline = monotonic() + 2
    start = after = -1
    try:
        with task_io_deadline(deadline):
            head = store.read_session_recovery_head(session_id, authority=authority)
            session = projections.get_session(session_id)
            workspace = None if workspaces is None else workspaces.get_workspace(session_id)
            if session is None or workspace is None:
                raise SessionRecoveryError("cloud recovery requires primary projections")
            frontier = head.index_sequence
            after = min(session.current_sequence, workspace.current_sequence, frontier)
            start = after
            while True:
                if after >= head.highwater:
                    # Primary/control-plane progress may have overtaken the old slice target.
                    # Re-capture under today's DB fence before declaring index readiness.
                    head = store.read_session_recovery_head(session_id, authority=authority)
                    if after >= head.highwater:
                        return session, workspace, head.highwater
                if monotonic() >= deadline:
                    raise TimeoutError("Session recovery preparation slice exhausted")
                page = store.read_session_event_page(
                    session_id,
                    after,
                    through_sequence=head.highwater,
                    limit=256,
                    max_bytes=1_048_576,
                )
                if (
                    page.session_id != session_id
                    or page.after_sequence != after
                    or (page.highwater != head.highwater)
                ):
                    raise SessionRecoveryError(
                        "Session recovery storage returned foreign coordinates"
                    )
                committed = store.commit_session_recovery_page(
                    page,
                    expected_index_sequence=frontier,
                    authority=authority.model_copy(update={"expected_stream_revision": after}),
                )
                session, workspace, frontier = (
                    committed.session,
                    committed.workspace,
                    committed.index_sequence,
                )
                after = min(session.current_sequence, workspace.current_sequence, frontier)
                if after < page.next_sequence:
                    raise SessionRecoveryError("Session recovery commit omitted durable coverage")
    except (TimeoutError, CheckpointNotReady, LockNotAvailable, QueryCanceled) as exc:
        # Final-page progress remains durable even if fenced readiness exceeds the slice.
        if start < after <= head.highwater:
            raise PreparationAdvanced(
                f"session-recovery:{authority.deployment_namespace}:{session_id}",
                through_sequence=after,
                highwater=head.highwater,
            ) from exc
        raise SessionRecoveryPending("Session recovery preparation slice exhausted") from exc
