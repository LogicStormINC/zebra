"""One bounded confirmation of a timed-out Worker write; never repeat the write."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.workspace_projection_store import (
    WorkerCommitConfirmationPending,
    WorkerProjectionCommitResult,
)
from psycopg import Error

from agent_storage.postgres.command_wakeup_receipts import HANDLED_EVENTS
from agent_storage.postgres.events import read_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.projections import get_session_in_transaction


def confirm_on_timeout(
    method: Callable[..., WorkerProjectionCommitResult],
) -> Callable[..., WorkerProjectionCommitResult]:
    @wraps(method)
    def commit(
        store: Any,
        event: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
        *,
        authority: WorkerMutationAuthority,
    ) -> WorkerProjectionCommitResult:
        try:
            return method(store, event, session, workspace, authority=authority)
        except TimeoutError as original:
            # ponytail: one 1s read within the remaining parent deadline, no write retry.
            # Uncertain/advanced state stays paused; a durable recovery protocol owns later work.
            try:
                confirmed = _confirm(store, event, session, workspace, authority)
            except (TimeoutError, Error) as error:
                raise WorkerCommitConfirmationPending(
                    "Worker commit confirmation unavailable"
                ) from error
            if confirmed is None:
                raise WorkerCommitConfirmationPending(
                    "Worker commit identity or frontier unconfirmed"
                ) from original
            return confirmed

    return commit


def _confirm(
    store: Any,
    event: SessionEvent,
    session: Session,
    workspace: WorkspaceProjection,
    authority: WorkerMutationAuthority,
) -> WorkerProjectionCommitResult | None:
    from agent_storage.postgres.workspaces import get_workspace_in_transaction

    database = store._database
    namespace = database.deployment_namespace
    # Recheck trust bindings before even reading canonical payloads.
    store._validate_worker_commit(event, session, workspace, authority)
    if event.sequence != authority.expected_stream_revision + 1:
        return None
    with database.connect_task_io(timeout_seconds=1) as connection:
        assert_current_lease_fence(connection, namespace, event.session_id, authority.lease_fence)
        # Same lock order as the writer. A newer command, cancellation or Turn prevents success.
        head = connection.execute(
            "SELECT current_version FROM session_streams "
            "WHERE deployment_namespace=%s AND session_id=%s FOR SHARE",
            (namespace, event.session_id),
        ).fetchone()
        if head is None or head["current_version"] != event.sequence:
            return None
        size = connection.execute(
            "SELECT octet_length(payload::text) AS bytes FROM session_events "
            "WHERE deployment_namespace=%s AND session_id=%s AND event_id=%s AND sequence=%s",
            (namespace, event.session_id, event.event_id, event.sequence),
        ).fetchone()
        if size is None or size["bytes"] > 1_048_576:
            return None
        canonical = read_event_in_transaction(connection, namespace, event.event_id)
        if canonical != event:
            return None
        stored_session = get_session_in_transaction(connection, namespace, event.session_id)
        stored_workspace = get_workspace_in_transaction(connection, namespace, event.session_id)
        if stored_session != session or stored_workspace != workspace:
            return None
        if event.event_type in HANDLED_EVENTS | {EventType.HARNESS_ATTEMPT_STARTED}:
            fence = authority.lease_fence
            receipts = connection.execute(
                "SELECT r.started_event_id, r.handled_event_id, p.status AS pending_status "
                "FROM command_handoff_receipts r LEFT JOIN session_command_pending p "
                "ON p.deployment_namespace=r.deployment_namespace "
                "AND p.accepted_event_id=r.accepted_event_id "
                "WHERE r.deployment_namespace=%s AND r.session_id=%s "
                "AND r.status='accepted' AND r.control_plane_epoch=%s "
                "AND r.fencing_token=%s AND r.owner_instance_id=%s",
                (
                    namespace,
                    event.session_id,
                    fence.control_plane_epoch,
                    fence.fencing_token,
                    fence.owner_instance_id,
                ),
            ).fetchall()
            # Conservative for legacy/partial handoffs: never infer a receipt from an Event.
            for receipt in receipts:
                if event.event_type is EventType.HARNESS_ATTEMPT_STARTED:
                    if str(receipt["started_event_id"]) != str(event.event_id):
                        return None
                elif (
                    str(receipt["handled_event_id"]) != str(event.event_id)
                    or receipt["pending_status"] != "done"
                ):
                    return None
        # Confirm ownership again after all reads; no stale fence or cancellation is hidden.
        assert_current_lease_fence(connection, namespace, event.session_id, authority.lease_fence)
        return WorkerProjectionCommitResult(event, stored_session, stored_workspace)
