"""One-connection PostgreSQL Handoff aggregate mutations."""

from typing import Any
from uuid import UUID

from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.identifiers import TaskId
from agent_core.domain.session_handoff import (
    HandoffOperationStatus,
    SessionHandoffEnvelope,
    SessionLineage,
)
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.session_handoff import (
    HandoffOperation,
    SessionHandoffCommitRequest,
    SessionHandoffResult,
    canonical_handoff_request_hash,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import lock_session_lease_boundary
from agent_storage.postgres.projections import (
    get_session_in_transaction,
    save_session_in_transaction,
)
from agent_storage.postgres.session_handoff_facts import (
    operation_from_row,
    read_source_facts_in_transaction,
    sha256_text,
)
from agent_storage.postgres.task_index_transactions import attach_segment_in_transaction
from agent_storage.postgres.task_lineage import rollover_reason_for_handoff
from agent_storage.postgres.workspaces import (
    get_workspace_in_transaction,
    save_workspace_in_transaction,
)
from agent_storage.session_handoff_events import build_handoff_events
from agent_storage.session_handoff_rows import HandoffStorageConflictError

_TERMINAL_SOURCE_STATUSES = {
    SessionStatus.COMPLETED,
    SessionStatus.CANCELLED,
    SessionStatus.SUSPENDED,
    SessionStatus.FAILED,
}


def commit_handoff_in_transaction(
    connection: Any,
    deployment_namespace: str,
    request: SessionHandoffCommitRequest,
) -> SessionHandoffResult:
    operation = lock_operation(
        connection,
        deployment_namespace,
        request.operation.operation_id,
    )
    if not _same_reservation(operation, request.operation):
        raise HandoffStorageConflictError("handoff reservation facts changed")
    _validate_request(operation, request)
    if operation.status is HandoffOperationStatus.COMMITTED:
        return result_for_operation(
            connection,
            deployment_namespace,
            operation,
            replay=True,
        )
    if operation.status is HandoffOperationStatus.ABORTED:
        raise HandoffStorageConflictError("handoff operation is aborted")
    lock_session_lease_boundary(
        connection,
        deployment_namespace,
        operation.source_session_id,
    )
    source_stream = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s FOR UPDATE
        """,
        (deployment_namespace, operation.source_session_id),
    ).fetchone()
    source = get_session_in_transaction(
        connection,
        deployment_namespace,
        operation.source_session_id,
    )
    workspace = get_workspace_in_transaction(
        connection,
        deployment_namespace,
        operation.source_session_id,
    )
    facts = read_source_facts_in_transaction(
        connection,
        deployment_namespace,
        operation.source_session_id,
        at=request.envelope.created_at,
        lock_workspace=True,
    )
    if source is None or workspace is None or source_stream is None:
        raise HandoffStorageConflictError("handoff source projections are incomplete")
    if source.status not in _TERMINAL_SOURCE_STATUSES or facts.has_active_lease:
        raise HandoffStorageConflictError("handoff source is not at a safe boundary")
    if (
        source.current_sequence != facts.stream_version
        or source_stream["current_version"] != facts.stream_version
        or facts.stream_version != operation.expected_source_stream_version
        or facts.lease_fence != operation.source_lease_fence
        or facts.authority_revision != operation.authority_revision
        or facts.workspace_revision != operation.workspace_revision
        or facts.task_profile_revision != operation.task_profile_revision
    ):
        raise HandoffStorageConflictError("handoff source reservation facts changed")
    segment = connection.execute(
        """
        SELECT segment.segment_index, task.active_segment_id
        FROM execution_segments segment
        JOIN agent_tasks task
          ON task.deployment_namespace = segment.deployment_namespace
         AND task.task_id = segment.task_id
        WHERE segment.deployment_namespace = %s
          AND segment.task_id = %s AND segment.session_id = %s
        FOR UPDATE OF task
        """,
        (
            deployment_namespace,
            TaskId(UUID(str(request.envelope.root_session_id))),
            operation.source_session_id,
        ),
    ).fetchone()
    if (
        segment is None
        or segment["active_segment_id"] != operation.source_session_id
        or segment["segment_index"] != request.envelope.source_stage_index
    ):
        raise HandoffStorageConflictError("handoff Task lineage changed")
    events = build_handoff_events(operation, request, workspace.model_dump(mode="json"))
    parent_event, child_events = events[0], list(events[1:])
    append_event_in_transaction(connection, deployment_namespace, parent_event)
    save_session_in_transaction(
        connection,
        deployment_namespace,
        apply_session_event(source, parent_event),
    )
    save_workspace_in_transaction(
        connection,
        deployment_namespace,
        apply_workspace_event(workspace, parent_event),
    )
    for event in child_events:
        append_event_in_transaction(connection, deployment_namespace, event)
    child = rebuild_session(child_events)
    child_workspace = rebuild_workspace(child_events).model_copy(
        update={
            "definition_snapshot": workspace.definition_snapshot,
            "runtime_name": workspace.runtime_name,
            "runtime_engine": workspace.runtime_engine,
            "runtime_image": workspace.runtime_image,
            "runtime_spec_digest": workspace.runtime_spec_digest,
            "runtime_network_enforcement": workspace.runtime_network_enforcement,
            "runtime_workspace_writable": workspace.runtime_workspace_writable,
            "snapshot_id": workspace.snapshot_id,
            "snapshot_path": workspace.snapshot_path,
        }
    )
    save_session_in_transaction(connection, deployment_namespace, child)
    save_workspace_in_transaction(connection, deployment_namespace, child_workspace)
    attach_segment_in_transaction(
        connection,
        deployment_namespace,
        task_id=TaskId(UUID(str(request.envelope.root_session_id))),
        segment_id=operation.target_session_id,
        predecessor_id=operation.source_session_id,
        reason=rollover_reason_for_handoff(request.envelope.reason.value),
    )
    _insert_envelope_and_dispatch(
        connection,
        deployment_namespace,
        operation,
        request,
    )
    row = connection.execute(
        """
        UPDATE handoff_operations
        SET status = 'committed', artifact_id = %s,
            updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND operation_id = %s
        RETURNING *
        """,
        (request.artifact_id, deployment_namespace, UUID(operation.operation_id)),
    ).fetchone()
    assert row is not None
    committed = operation_from_row(row)
    return SessionHandoffResult(
        handoff_id=committed.handoff_id,
        source_session_id=committed.source_session_id,
        child_session_id=committed.target_session_id,
        lineage=SessionLineage(
            session_id=committed.target_session_id,
            root_session_id=request.envelope.root_session_id,
            parent_session_id=committed.source_session_id,
            inbound_handoff_id=committed.handoff_id,
            stage_index=request.envelope.target_stage_index,
        ),
        artifact_id=request.artifact_id,
        checksum=request.envelope.checksum,
        child_status=child.status.value,
    )


def lock_operation(
    connection: Any,
    deployment_namespace: str,
    operation_id: str,
) -> HandoffOperation:
    row = connection.execute(
        """
        SELECT * FROM handoff_operations
        WHERE deployment_namespace = %s AND operation_id = %s
        FOR UPDATE
        """,
        (deployment_namespace, UUID(operation_id)),
    ).fetchone()
    if row is None:
        raise HandoffStorageConflictError("handoff operation not found")
    return operation_from_row(row)


def result_for_operation(
    connection: Any,
    deployment_namespace: str,
    operation: HandoffOperation,
    *,
    replay: bool,
) -> SessionHandoffResult:
    row = connection.execute(
        """
        SELECT envelope, checksum, artifact_id FROM session_handoff_envelopes
        WHERE deployment_namespace = %s AND handoff_id = %s
        """,
        (deployment_namespace, operation.handoff_id),
    ).fetchone()
    if row is None or operation.artifact_id is None:
        raise HandoffStorageConflictError("committed handoff is incomplete")
    envelope = SessionHandoffEnvelope.model_validate(row["envelope"])
    child = get_session_in_transaction(
        connection,
        deployment_namespace,
        operation.target_session_id,
    )
    if child is None or row["artifact_id"] != operation.artifact_id:
        raise HandoffStorageConflictError("committed handoff facts conflict")
    return SessionHandoffResult(
        handoff_id=operation.handoff_id,
        source_session_id=operation.source_session_id,
        child_session_id=operation.target_session_id,
        lineage=SessionLineage(
            session_id=operation.target_session_id,
            root_session_id=envelope.root_session_id,
            parent_session_id=operation.source_session_id,
            inbound_handoff_id=operation.handoff_id,
            stage_index=envelope.target_stage_index,
        ),
        artifact_id=operation.artifact_id,
        checksum=row["checksum"],
        child_status=child.status.value,
        idempotent_replay=replay,
    )


def _insert_envelope_and_dispatch(
    connection: Any,
    deployment_namespace: str,
    operation: HandoffOperation,
    request: SessionHandoffCommitRequest,
) -> None:
    connection.execute(
        """
        INSERT INTO session_handoff_envelopes (
            deployment_namespace, handoff_id, source_session_id,
            target_session_id, artifact_id, envelope, checksum, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            deployment_namespace,
            operation.handoff_id,
            operation.source_session_id,
            operation.target_session_id,
            request.artifact_id,
            Jsonb(request.envelope.model_dump(mode="json")),
            request.envelope.checksum,
            request.envelope.created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO handoff_dispatch_outbox (
            deployment_namespace, delivery_id, child_session_id,
            handoff_id, status, created_at
        ) VALUES (%s, %s, %s, %s, 'pending', %s)
        """,
        (
            deployment_namespace,
            operation.target_session_id,
            operation.target_session_id,
            operation.handoff_id,
            request.envelope.created_at,
        ),
    )


def _validate_request(
    operation: HandoffOperation,
    request: SessionHandoffCommitRequest,
) -> None:
    envelope = request.envelope
    if (
        not request.artifact_id.strip()
        or request.create_request.source_session_id != operation.source_session_id
        or sha256_text(request.create_request.idempotency_key) != operation.idempotency_key_hash
        or envelope.handoff_id != operation.handoff_id
        or envelope.source_session_id != operation.source_session_id
        or envelope.target_session_id != operation.target_session_id
        or envelope.workspace_revision != operation.workspace_revision
        or envelope.reason != request.create_request.reason
        or envelope.focus != request.create_request.focus
        or envelope.immediate_next != request.create_request.stage_prompt
        or canonical_handoff_request_hash(
            request.create_request,
            objective=envelope.objective,
            completed_work=envelope.completed_work,
            pending_work=envelope.pending_work,
        )
        != operation.request_hash
        or envelope.target_stage_index > operation.effective_depth_limit
        or envelope.checksum != envelope.expected_checksum()
    ):
        raise HandoffStorageConflictError("handoff request does not match reservation")


def _same_reservation(stored: HandoffOperation, supplied: HandoffOperation) -> bool:
    return (
        stored.operation_id,
        stored.source_session_id,
        stored.target_session_id,
        stored.handoff_id,
        stored.idempotency_key_hash,
        stored.request_hash,
        stored.expected_source_stream_version,
        stored.source_lease_fence,
        stored.authority_revision,
        stored.workspace_revision,
        stored.task_profile_revision,
        stored.effective_depth_limit,
        stored.created_at,
    ) == (
        supplied.operation_id,
        supplied.source_session_id,
        supplied.target_session_id,
        supplied.handoff_id,
        supplied.idempotency_key_hash,
        supplied.request_hash,
        supplied.expected_source_stream_version,
        supplied.source_lease_fence,
        supplied.authority_revision,
        supplied.workspace_revision,
        supplied.task_profile_revision,
        supplied.effective_depth_limit,
        supplied.created_at,
    )
