"""Worker and administrative governed Memory transaction orchestration."""

from typing import Any

from agent_core.application.memory_reviews import (
    MemoryReviewAction,
    MemoryReviewCommand,
    MemoryReviewService,
)
from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventType
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryEntry,
)
from agent_core.domain.governed_memory_operations import (
    AdministrativeMemoryReviewRequest,
    GovernedMemoryOperationKind,
    WorkerMemoryMutationPlan,
)
from agent_core.domain.governed_memory_receipts import (
    GovernedMemoryCommitResult,
)
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryRecord
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS, WorkerMutationAuthority

from agent_storage.postgres.governed_memory_rows import authority_from_row
from agent_storage.postgres.governed_memory_transaction_support import (
    _append_events,
    _apply_mutation,
    _create_or_get,
    _lock_mutations,
    _lock_operation,
    _lock_scopes,
    _lock_session,
    _operation_replay,
    _replace_record,
    _revision_for,
    _rewrite_event,
    _scope_column,
    _scope_value,
    _store_receipt,
)
from agent_storage.postgres.leases import (
    assert_current_lease_fence,
    lock_session_lease_boundary,
)
from agent_storage.postgres.projections import save_session_in_transaction
from agent_storage.postgres.workspaces import (
    get_workspace_in_transaction,
    save_workspace_in_transaction,
)


def commit_worker(
    connection: Any,
    namespace: str,
    plan: WorkerMemoryMutationPlan,
    authority: WorkerMutationAuthority,
) -> GovernedMemoryCommitResult:
    plan.validate_for(namespace, authority)
    _validate_worker_mapping(plan)
    _lock_operation(connection, namespace, plan.operation_id)
    replay = _operation_replay(
        connection,
        namespace,
        plan.operation_id,
        GovernedMemoryOperationKind.WORKER_CANDIDATES,
        plan.request_digest,
        plan.session_id,
    )
    if replay is not None:
        return replay
    assert_current_lease_fence(connection, namespace, plan.session_id, authority.lease_fence)
    session = _lock_session(connection, namespace, plan.session_id, plan.expected_stream_revision)
    existing_rows = [
        connection.execute(
            """SELECT * FROM governed_memory_records
            WHERE deployment_namespace = %s AND memory_id = %s""",
            (namespace, mutation.memory_id),
        ).fetchone()
        for mutation in plan.lifecycle_mutations
    ]
    existing_entries = [
        item.record
        for row in existing_rows
        if row is not None and isinstance((item := authority_from_row(row)), GovernedMemoryEntry)
    ]
    _lock_scopes(
        connection,
        namespace,
        tuple([*(creation.record for creation in plan.creations), *existing_entries]),
    )
    canonical_entries: list[GovernedMemoryEntry] = []
    id_map: dict[str, MemoryId] = {}
    for creation in sorted(plan.creations, key=lambda item: item.creation_key):
        stored = _create_or_get(connection, namespace, creation)
        canonical_entries.append(stored)
        id_map[str(creation.record.memory_id)] = stored.record.memory_id
    canonical_mutations = tuple(
        mutation.model_copy(
            update={
                "memory_id": id_map.get(str(mutation.memory_id), mutation.memory_id),
                "superseded_by": (
                    None
                    if mutation.superseded_by is None
                    else id_map.get(str(mutation.superseded_by), mutation.superseded_by)
                ),
            }
        )
        for mutation in plan.lifecycle_mutations
    )
    mutations = _lock_mutations(connection, namespace, canonical_mutations)
    mutations.sort(key=lambda item: (item[0].status.value == "confirmed", str(item[0].memory_id)))
    mutated = [
        _apply_mutation(connection, namespace, mutation, row, id_map) for mutation, row in mutations
    ]
    canonical_events = _append_events(
        connection,
        namespace,
        tuple(
            _rewrite_event(
                event,
                {source: str(target) for source, target in id_map.items()},
                sequence=plan.expected_stream_revision + index + 1,
            )
            for index, event in enumerate(plan.events)
        ),
        plan.expected_stream_revision,
    )
    stored_session = _save_projections(connection, namespace, session, canonical_events)
    return _store_receipt(
        connection,
        namespace,
        operation_id=plan.operation_id,
        operation_kind=GovernedMemoryOperationKind.WORKER_CANDIDATES,
        request_digest=plan.request_digest,
        records=tuple([*canonical_entries, *mutated]),
        events=canonical_events,
        projection_revision=stored_session.current_sequence,
    )


def commit_administrative(
    connection: Any,
    namespace: str,
    request: AdministrativeMemoryReviewRequest,
    authority: AdministrativeMutationCAS,
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
        raise GovernedMemoryConflictError("administrative Memory review has an active Lease")
    session = _lock_session(
        connection, namespace, request.session_id, request.expected_stream_revision
    )
    candidate_row = connection.execute(
        """SELECT * FROM governed_memory_records
        WHERE deployment_namespace = %s AND memory_id = %s""",
        (namespace, request.memory_id),
    ).fetchone()
    if candidate_row is None:
        raise GovernedMemoryConflictError("governed Memory was not found")
    candidate = authority_from_row(candidate_row)
    if not isinstance(candidate, GovernedMemoryEntry):
        raise GovernedMemoryConflictError("administrative review target is deleted")
    if candidate.revision != request.expected_revision:
        raise GovernedMemoryConflictError("administrative review Memory revision changed")
    _lock_scopes(connection, namespace, (candidate.record,))
    locked_rows = connection.execute(
        f"""
        SELECT * FROM governed_memory_records
        WHERE deployment_namespace = %s
          AND memory_type = %s AND visibility = %s
          AND {_scope_column(candidate.record.visibility)} = %s
          AND (memory_id = %s OR status = 'confirmed')
        ORDER BY memory_id FOR UPDATE
        """,
        (
            namespace,
            candidate.record.memory_type.value,
            candidate.record.visibility.value,
            _scope_value(candidate.record),
            request.memory_id,
        ),
    ).fetchall()
    candidate_row = next(
        (row for row in locked_rows if row["memory_id"] == request.memory_id), None
    )
    if candidate_row is None:
        raise GovernedMemoryConflictError("administrative review target changed scope")
    candidate = authority_from_row(candidate_row)
    if (
        not isinstance(candidate, GovernedMemoryEntry)
        or candidate.revision != request.expected_revision
    ):
        raise GovernedMemoryConflictError("administrative review Memory revision changed")
    confirmed_rows = [row for row in locked_rows if row["status"] == "confirmed"]
    existing = tuple(
        entry.record
        for row in confirmed_rows
        if isinstance((entry := authority_from_row(row)), GovernedMemoryEntry)
    )
    review = MemoryReviewService().plan(
        session=session,
        record=candidate.record,
        next_sequence=request.expected_stream_revision + 1,
        command=MemoryReviewCommand(
            action=MemoryReviewAction(request.action.value),
            operator=request.operator,
            reason=request.reason,
            actor=request.actor,
            created_at=request.created_at,
        ),
        existing_records=existing,
    )
    changed = [
        *(
            _replace_record(
                connection,
                namespace,
                record,
                _revision_for(confirmed_rows, record.memory_id),
            )
            for record in review.superseded_records
        ),
        _replace_record(connection, namespace, review.record, candidate.revision),
    ]
    events = _append_events(
        connection, namespace, (review.event,), request.expected_stream_revision
    )
    stored_session = _save_projections(connection, namespace, session, events)
    return _store_receipt(
        connection,
        namespace,
        operation_id=request.operation_id,
        operation_kind=GovernedMemoryOperationKind.ADMINISTRATIVE_REVIEW,
        request_digest=request.request_digest,
        records=tuple(changed),
        events=events,
        projection_revision=stored_session.current_sequence,
    )


def _save_projections(
    connection: Any, namespace: str, session: Any, events: tuple[Any, ...]
) -> Any:
    workspace = get_workspace_in_transaction(connection, namespace, session.session_id)
    if workspace is None:
        raise GovernedMemoryConflictError("Memory aggregate requires a Workspace projection")
    for event in events:
        session = apply_session_event(session, event)
        workspace = apply_workspace_event(workspace, event)
    saved_session = save_session_in_transaction(connection, namespace, session)
    saved_workspace = save_workspace_in_transaction(connection, namespace, workspace)
    if saved_workspace.current_sequence != saved_session.current_sequence:
        raise GovernedMemoryConflictError("Memory projections did not reach one revision")
    return saved_session


def _validate_worker_mapping(plan: WorkerMemoryMutationPlan) -> None:
    creation_ids = [str(item.record.memory_id) for item in plan.creations]
    creation_keys = [item.creation_key for item in plan.creations]
    mutation_ids = [str(item.memory_id) for item in plan.lifecycle_mutations]
    if len(set(creation_ids)) != len(creation_ids) or len(set(creation_keys)) != len(creation_keys):
        raise GovernedMemoryConflictError("Worker Memory creations are not unique")
    if len(set(mutation_ids)) != len(mutation_ids):
        raise GovernedMemoryConflictError("Worker Memory lifecycle target is duplicated")
    if any(item.record.source_session_id != plan.session_id for item in plan.creations):
        raise GovernedMemoryConflictError("Worker Memory creation source Session changed")
    candidate_events = [
        event for event in plan.events if event.event_type is EventType.MEMORY_CANDIDATE_EXTRACTED
    ]
    review_events = [
        event for event in plan.events if event.event_type is EventType.MEMORY_REVIEW_RECORDED
    ]
    if len(candidate_events) + len(review_events) != len(plan.events):
        raise GovernedMemoryConflictError("Worker Memory aggregate has an unrelated Event")
    for creation in plan.creations:
        matches = [
            event
            for event in candidate_events
            if event.payload == _candidate_event_payload(creation.record)
        ]
        if len(matches) != 1:
            raise GovernedMemoryConflictError("Memory creation Event mapping is not unique")
    if len(candidate_events) != len(plan.creations):
        raise GovernedMemoryConflictError("Worker Memory has an extra creation Event")
    main_mutations = [
        item for item in plan.lifecycle_mutations if item.status.value != "superseded"
    ]
    for mutation in main_mutations:
        matches = [
            event
            for event in review_events
            if event.payload.get("memory_id") == str(mutation.memory_id)
            and event.payload.get("previous_status") == mutation.previous_status.value
            and event.payload.get("status") == mutation.status.value
        ]
        if len(matches) != 1:
            raise GovernedMemoryConflictError("Memory review Event mapping is not unique")
    if len(review_events) != len(main_mutations):
        raise GovernedMemoryConflictError("Worker Memory has an extra review Event")
    for event in review_events:
        superseded_ids = event.payload.get("superseded_memory_ids")
        if not isinstance(superseded_ids, list) or any(
            not isinstance(memory_id, str) for memory_id in superseded_ids
        ):
            raise GovernedMemoryConflictError("Memory review Event supersession list is invalid")
        expected = sorted(
            str(mutation.memory_id)
            for mutation in plan.lifecycle_mutations
            if mutation.status.value == "superseded"
            and str(mutation.superseded_by) == event.payload.get("memory_id")
        )
        if sorted(superseded_ids) != expected or len(set(superseded_ids)) != len(superseded_ids):
            raise GovernedMemoryConflictError("Memory supersession Event mapping is not exact")


def _candidate_event_payload(record: MemoryRecord) -> dict[str, object]:
    return {
        "memory_id": str(record.memory_id),
        "memory_type": record.memory_type.value,
        "status": record.status.value,
        "visibility": record.visibility.value,
        "text": record.text,
        "confidence": record.confidence,
        "source_event_start": record.source_event_start,
        "source_event_end": record.source_event_end,
        "repo_id": record.repo_id,
        "user_id": record.user_id,
        "tenant_id": record.tenant_id,
    }
