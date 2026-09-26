"""Atomic correction of confirmed governed Memory."""

from typing import Any

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.governed_memories import GovernedMemoryConflictError, GovernedMemoryEntry
from agent_core.domain.governed_memory_operations import (
    AdministrativeMemoryReplacementRequest,
    GovernedMemoryOperationKind,
)
from agent_core.domain.governed_memory_receipts import GovernedMemoryCommitResult
from agent_core.domain.memories import MemoryRecord, MemoryStatus
from agent_core.domain.memory_delivery import MemoryDeliveryScope
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS

from agent_storage.postgres.governed_memory_rows import authority_from_row
from agent_storage.postgres.governed_memory_transaction_support import (
    _append_events,
    _create_or_get,
    _enqueue_authority_delivery,
    _lock_operation,
    _lock_scopes,
    _lock_session,
    _operation_replay,
    _replace_record,
    _store_receipt,
)
from agent_storage.postgres.governed_memory_transactions import (
    _candidate_event_payload,
    _save_projections,
)
from agent_storage.postgres.leases import lock_session_lease_boundary


def commit_administrative_replacement(
    connection: Any,
    namespace: str,
    request: AdministrativeMemoryReplacementRequest,
    authority: AdministrativeMutationCAS,
    *,
    delivery_scope: MemoryDeliveryScope | None = None,
) -> GovernedMemoryCommitResult:
    request.validate_for(namespace, authority)
    _lock_operation(connection, namespace, request.operation_id)
    replay = _operation_replay(
        connection,
        namespace,
        request.operation_id,
        GovernedMemoryOperationKind.ADMINISTRATIVE_REVIEW,
        request.request_digest,
        request.session_id,
    )
    if replay is not None:
        return replay
    lock_session_lease_boundary(connection, namespace, request.session_id)
    active = connection.execute(
        """
        SELECT 1 FROM worker_leases
        WHERE deployment_namespace = %s AND session_id = %s
          AND released_at IS NULL AND expires_at > transaction_timestamp()
        """,
        (namespace, request.session_id),
    ).fetchone()
    if active is not None:
        raise GovernedMemoryConflictError("administrative Memory replacement has an active Lease")
    session = _lock_session(
        connection, namespace, request.session_id, request.expected_stream_revision
    )
    prior_row = connection.execute(
        """SELECT * FROM governed_memory_records
        WHERE deployment_namespace = %s AND memory_id = %s""",
        (namespace, request.memory_id),
    ).fetchone()
    prior = None if prior_row is None else authority_from_row(prior_row)
    if not isinstance(prior, GovernedMemoryEntry):
        raise GovernedMemoryConflictError("replacement target was not found")
    if prior.revision != request.expected_revision or (
        prior.record.status is not MemoryStatus.CONFIRMED
    ):
        raise GovernedMemoryConflictError("replacement target revision or status changed")
    replacement = request.replacement.record
    if replacement.memory_type is not prior.record.memory_type or not _same_scope(
        replacement, prior.record
    ):
        raise GovernedMemoryConflictError("replacement changed Memory type or scope")
    _lock_scopes(connection, namespace, (prior.record, replacement))
    prior_row = connection.execute(
        """SELECT * FROM governed_memory_records
        WHERE deployment_namespace = %s AND memory_id = %s FOR UPDATE""",
        (namespace, request.memory_id),
    ).fetchone()
    prior = None if prior_row is None else authority_from_row(prior_row)
    if not isinstance(prior, GovernedMemoryEntry) or (
        prior.revision != request.expected_revision
        or prior.record.status is not MemoryStatus.CONFIRMED
    ):
        raise GovernedMemoryConflictError("replacement target revision or status changed")
    created = _create_or_get(connection, namespace, request.replacement)
    if created.record.status is not MemoryStatus.CANDIDATE or created.revision != 1:
        raise GovernedMemoryConflictError("replacement candidate was already mutated")
    superseded = _replace_record(
        connection,
        namespace,
        prior.record.model_copy(
            update={
                "status": MemoryStatus.SUPERSEDED,
                "superseded_by": created.record.memory_id,
                "updated_at": request.created_at,
            }
        ),
        prior.revision,
    )
    confirmed = _replace_record(
        connection,
        namespace,
        created.record.model_copy(
            update={"status": MemoryStatus.CONFIRMED, "updated_at": request.created_at}
        ),
        created.revision,
    )
    events = _replacement_events(request, created, prior)
    canonical_events = _append_events(
        connection, namespace, events, request.expected_stream_revision
    )
    stored_session = _save_projections(connection, namespace, session, canonical_events)
    changed = (confirmed, superseded)
    _enqueue_authority_delivery(connection, namespace, delivery_scope, changed)
    return _store_receipt(
        connection,
        namespace,
        operation_id=request.operation_id,
        operation_kind=GovernedMemoryOperationKind.ADMINISTRATIVE_REVIEW,
        request_digest=request.request_digest,
        records=changed,
        events=canonical_events,
        projection_revision=stored_session.current_sequence,
    )


def _replacement_events(
    request: AdministrativeMemoryReplacementRequest,
    created: GovernedMemoryEntry,
    prior: GovernedMemoryEntry,
) -> tuple[SessionEvent, SessionEvent]:
    return (
        SessionEvent.create(
            session_id=request.session_id,
            sequence=request.expected_stream_revision + 1,
            event_type=EventType.MEMORY_CANDIDATE_EXTRACTED,
            actor=request.actor,
            payload=_candidate_event_payload(created.record),
            created_at=request.created_at,
        ),
        SessionEvent.create(
            session_id=request.session_id,
            sequence=request.expected_stream_revision + 2,
            event_type=EventType.MEMORY_REVIEW_RECORDED,
            actor=request.actor,
            payload={
                "memory_id": str(created.record.memory_id),
                "memory_type": created.record.memory_type.value,
                "previous_status": MemoryStatus.CANDIDATE.value,
                "status": MemoryStatus.CONFIRMED.value,
                "operator": request.operator,
                "reason": request.reason,
                "superseded_memory_ids": [str(prior.record.memory_id)],
                "duplicate_of_memory_id": None,
            },
            created_at=request.created_at,
        ),
    )


def _same_scope(left: MemoryRecord, right: MemoryRecord) -> bool:
    return left.visibility is right.visibility and all(
        getattr(left, field) == getattr(right, field)
        for field in (
            "tenant_id",
            "user_id",
            "repo_id",
            "authority_issuer",
            "namespace_id",
            "definition_id",
        )
    )
