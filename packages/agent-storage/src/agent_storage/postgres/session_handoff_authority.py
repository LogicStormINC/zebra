"""PostgreSQL authority and CAS helpers for Handoff reservation lifecycle."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import (
    HandoffOperationStatus,
    WorkspaceBindingRevision,
)
from agent_core.ports.session_handoff import (
    HandoffOperation,
    HandoffSourceFacts,
    SessionHandoffAbortRequest,
)

from agent_storage.postgres.leases import lock_session_lease_boundary
from agent_storage.postgres.session_handoff_facts import (
    operation_from_row,
    read_source_facts_in_transaction,
)
from agent_storage.postgres.session_handoff_transactions import (
    _same_reservation,
    lock_operation,
)
from agent_storage.session_handoff_rows import HandoffStorageConflictError


def find_reservation(
    connection: Any,
    namespace: str,
    source_session_id: SessionId,
    idempotency_hash: str,
) -> dict[str, object] | None:
    row = connection.execute(
        """
        SELECT * FROM handoff_operations
        WHERE deployment_namespace = %s AND source_session_id = %s
          AND idempotency_key_hash = %s
        FOR UPDATE
        """,
        (namespace, source_session_id, idempotency_hash),
    ).fetchone()
    return cast(dict[str, object] | None, row)


def require_reservation_facts(
    facts: HandoffSourceFacts,
    *,
    expected_source_stream_version: int,
    source_lease_fence: LeaseFence | None,
    authority_revision: str,
    workspace_revision: WorkspaceBindingRevision,
    task_profile_revision: str,
) -> None:
    if facts.has_active_lease:
        raise HandoffStorageConflictError("handoff source still has an active lease")
    if (
        facts.stream_version != expected_source_stream_version
        or facts.lease_fence != source_lease_fence
        or facts.authority_revision != authority_revision
        or facts.workspace_revision != workspace_revision
        or facts.task_profile_revision != task_profile_revision
    ):
        raise HandoffStorageConflictError("handoff source authority facts changed")


def abort_authorized_in_transaction(
    connection: Any,
    namespace: str,
    request: SessionHandoffAbortRequest,
) -> HandoffOperation:
    current = lock_operation(connection, namespace, request.operation.operation_id)
    if not _same_reservation(current, request.operation):
        raise HandoffStorageConflictError("handoff abort reservation facts changed")
    authority = request.authority
    if (
        authority.deployment_namespace != namespace
        or authority.session_id != current.source_session_id
        or authority.expected_stream_revision != current.expected_source_stream_version
    ):
        raise HandoffStorageConflictError("handoff abort authority does not match reservation")
    if current.status is HandoffOperationStatus.COMMITTED:
        raise HandoffStorageConflictError("committed handoff cannot be aborted")
    if current.status is HandoffOperationStatus.ABORTED:
        if current.abort_code != request.code:
            raise HandoffStorageConflictError("handoff abort request identity was reused")
        return current
    lock_session_lease_boundary(connection, namespace, current.source_session_id)
    try:
        facts = read_source_facts_in_transaction(
            connection,
            namespace,
            current.source_session_id,
            at=current.updated_at,
            lock_workspace=True,
            lock_stream=True,
        )
    except ValueError as error:
        raise HandoffStorageConflictError(
            "handoff abort source authority facts are unavailable"
        ) from error
    require_reservation_facts(
        facts,
        expected_source_stream_version=current.expected_source_stream_version,
        source_lease_fence=current.source_lease_fence,
        authority_revision=current.authority_revision,
        workspace_revision=current.workspace_revision,
        task_profile_revision=current.task_profile_revision,
    )
    row = connection.execute(
        """
        UPDATE handoff_operations
        SET status = 'aborted', abort_code = %s,
            updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND operation_id = %s
          AND status = 'preparing'
          AND request_hash = %s
          AND expected_source_stream_version = %s
        RETURNING *
        """,
        (
            request.code,
            namespace,
            UUID(current.operation_id),
            current.request_hash,
            current.expected_source_stream_version,
        ),
    ).fetchone()
    if row is None:
        raise HandoffStorageConflictError("handoff abort CAS lost the operation")
    return operation_from_row(row)
