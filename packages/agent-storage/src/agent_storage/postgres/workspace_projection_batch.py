"""Project a bounded canonical companion tail once, under a fresh lease fence."""

from typing import Any

from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.workspace_projection_store import WorkerProjectionCommitResult

from agent_storage.postgres.command_wakeup_receipts import record_worker_command_boundary
from agent_storage.postgres.leases import assert_current_lease_fence, lock_session_lease_boundary
from agent_storage.postgres.projections import (
    get_session_in_transaction,
    save_session_in_transaction,
)


def project_batch(
    connection: Any, deployment: str, events: tuple[SessionEvent, ...], session: Session,
    workspace: WorkspaceProjection, authority: WorkerMutationAuthority,
) -> WorkerProjectionCommitResult:
    from agent_storage.postgres.workspaces import (
        PostgresWorkspaceProjectionConflictError as Conflict,
    )
    from agent_storage.postgres.workspaces import (
        get_workspace_in_transaction,
        save_workspace_in_transaction,
    )

    if not 1 <= len(events) <= 128 or authority.deployment_namespace != deployment:
        raise Conflict("invalid bounded Worker projection batch")
    if (session.session_id != authority.session_id or workspace.session_id != authority.session_id
            or any(event.session_id != authority.session_id or event.sequence !=
                   authority.expected_stream_revision + offset
                   for offset, event in enumerate(events, start=1))):
        raise Conflict("Worker projection batch skips canonical revisions or scope")
    lock_session_lease_boundary(connection, deployment, authority.session_id)
    assert_current_lease_fence(connection, deployment, authority.session_id, authority.lease_fence)
    stream = connection.execute(
        """SELECT current_version FROM session_streams
           WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE""",
        (deployment, authority.session_id),
    ).fetchone()
    if stream is None or stream["current_version"] < events[-1].sequence:
        raise Conflict("Worker projection batch is ahead of its stream")
    # Native byte bounds reject a corrupt/oversized source page before transferring
    # bodies. Canonical source rows remain pinned until both projections commit.
    rows = connection.execute(
        """SELECT e.* FROM session_events e WHERE deployment_namespace=%s
           AND session_id=%s AND sequence>%s AND sequence<=%s
           AND (SELECT sum(event_bytes_bound) FROM session_events
                WHERE deployment_namespace=%s AND session_id=%s
                  AND sequence>%s AND sequence<=%s
                HAVING count(*)=count(event_bytes_bound))<=33554432
           ORDER BY sequence LIMIT 129 FOR SHARE""",
        (deployment, authority.session_id, authority.expected_stream_revision, events[-1].sequence,
         deployment, authority.session_id, authority.expected_stream_revision, events[-1].sequence),
    ).fetchall()
    if tuple(SessionEvent.model_validate(row) for row in rows) != events:
        raise Conflict("Worker projection batch disagrees with canonical Events")
    current_session = get_session_in_transaction(connection, deployment, authority.session_id)
    current_workspace = get_workspace_in_transaction(connection, deployment, authority.session_id)
    if current_session is None:
        raise Conflict("Worker projection batch requires an existing Session projection")
    if current_session.current_sequence == events[-1].sequence:
        if current_session != session or current_workspace != workspace:
            raise Conflict("Worker projection batch conflicts with applied projections")
    else:
        if (current_session.current_sequence != authority.expected_stream_revision
                or (current_workspace is not None and current_workspace.current_sequence
                    != authority.expected_stream_revision)):
            raise Conflict("Worker projection batch does not follow both projections")
        for event in events:
            current_session = apply_session_event(current_session, event)
            if current_workspace is None:
                if event.event_type is not EventType.TASK_PREPARED:
                    raise Conflict("first workspace projection requires TASK_PREPARED")
                current_workspace = rebuild_workspace([event])
            else:
                current_workspace = apply_workspace_event(current_workspace, event)
        if current_session != session or current_workspace != workspace:
            raise Conflict("Worker projection batch content is not derived from Events")
        current_session = save_session_in_transaction(connection, deployment, current_session)
        assert current_workspace is not None
        current_workspace = save_workspace_in_transaction(connection, deployment, current_workspace)
    # Lock waits above may outlive the lease. Recheck at the actual write boundary.
    assert_current_lease_fence(connection, deployment, authority.session_id, authority.lease_fence)
    for event in events:
        record_worker_command_boundary(connection, event, authority)
    assert current_workspace is not None
    return WorkerProjectionCommitResult(events[-1], current_session, current_workspace)
