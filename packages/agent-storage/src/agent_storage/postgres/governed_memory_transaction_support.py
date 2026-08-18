"""Locks, row CAS and canonical receipts for governed Memory transactions."""

from typing import Any, cast

from agent_core.domain.events import SessionEvent
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryCreate,
    GovernedMemoryEntry,
    GovernedMemoryLifecycleMutation,
    GovernedMemoryTombstone,
)
from agent_core.domain.governed_memory_operations import (
    GovernedMemoryOperationKind,
)
from agent_core.domain.governed_memory_receipts import (
    GovernedMemoryCommitResult,
    GovernedMemoryOperationReceipt,
    GovernedMemoryRevision,
)
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryVisibility
from agent_core.domain.memory_delivery import (
    MemoryDeliveryOperation,
    MemoryDeliveryOperationRecord,
    MemoryDeliveryScope,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.governed_memory_receipt_reads import read_operation_receipt
from agent_storage.postgres.governed_memory_rows import (
    authority_from_row,
    memory_values,
)
from agent_storage.postgres.memory_delivery_errors import MemoryDeliveryConflictError
from agent_storage.postgres.memory_delivery_transaction_support import (
    enqueue_in_transaction,
)
from agent_storage.postgres.projections import get_session_in_transaction


def _lock_operation(connection: Any, namespace: str, operation_id: str) -> None:
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"memory-operation:{namespace}:{operation_id}",),
    )


def _lock_session(connection: Any, namespace: str, session_id: SessionId, expected: int) -> Any:
    row = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s FOR UPDATE
        """,
        (namespace, session_id),
    ).fetchone()
    if row is None or row["current_version"] != expected:
        raise GovernedMemoryConflictError("Memory Session stream revision changed")
    session = get_session_in_transaction(connection, namespace, session_id)
    if session is None or session.current_sequence != expected:
        raise GovernedMemoryConflictError("Memory Session projection revision changed")
    return session


def _lock_scope(connection: Any, namespace: str, record: MemoryRecord) -> None:
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (
            f"memory-scope:{namespace}:{record.visibility.value}:"
            f"{_scope_value(record)}:{record.memory_type.value}",
        ),
    )


def _lock_scopes(connection: Any, namespace: str, records: tuple[MemoryRecord, ...]) -> None:
    keys = sorted(
        {
            (record.visibility.value, _scope_value(record), record.memory_type.value)
            for record in records
        }
    )
    for visibility, scope, memory_type in keys:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"memory-scope:{namespace}:{visibility}:{scope}:{memory_type}",),
        )


def _lock_mutations(
    connection: Any,
    namespace: str,
    mutations: tuple[GovernedMemoryLifecycleMutation, ...],
) -> list[tuple[GovernedMemoryLifecycleMutation, dict[str, Any]]]:
    ids = {
        item
        for mutation in mutations
        for item in (mutation.memory_id, mutation.superseded_by)
        if item is not None
    }
    rows = {
        MemoryId(row["memory_id"]): row
        for memory_id in sorted(ids, key=str)
        if (row := _lock_memory(connection, namespace, memory_id)) is not None
    }
    result = []
    for mutation in mutations:
        row = rows[mutation.memory_id]
        authority = authority_from_row(row)
        if not isinstance(authority, GovernedMemoryEntry):
            raise GovernedMemoryConflictError("Memory lifecycle target is deleted")
        result.append((mutation, row))
        if mutation.superseded_by is not None:
            target = authority_from_row(rows[mutation.superseded_by])
            if isinstance(target, GovernedMemoryTombstone):
                raise GovernedMemoryConflictError("superseded_by cannot target deleted Memory")
    return result


def _lock_memory(connection: Any, namespace: str, memory_id: MemoryId) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT * FROM governed_memory_records
        WHERE deployment_namespace = %s AND memory_id = %s FOR UPDATE
        """,
        (namespace, memory_id),
    ).fetchone()
    if row is None:
        raise GovernedMemoryConflictError("governed Memory was not found")
    return cast(dict[str, Any], row)


def _create_or_get(
    connection: Any, namespace: str, creation: GovernedMemoryCreate
) -> GovernedMemoryEntry:
    rows = connection.execute(
        """
        SELECT * FROM governed_memory_records
        WHERE deployment_namespace = %s AND (creation_key = %s OR memory_id = %s)
        ORDER BY memory_id FOR UPDATE
        """,
        (namespace, creation.creation_key, creation.record.memory_id),
    ).fetchall()
    if rows:
        if len(rows) != 1 or rows[0]["creation_key"] != creation.creation_key:
            raise GovernedMemoryConflictError("Memory ID and creation key disagree")
        row = rows[0]
        stored = authority_from_row(row)
        if (
            not isinstance(stored, GovernedMemoryEntry)
            or stored.content_digest != creation.content_digest
        ):
            raise GovernedMemoryConflictError("Memory creation key content changed")
        return stored
    entry = GovernedMemoryEntry(
        deployment_namespace=namespace,
        record=creation.record,
        revision=1,
        creation_key=creation.creation_key,
        content_digest=creation.content_digest,
    )
    row = connection.execute(
        """
        INSERT INTO governed_memory_records (
            deployment_namespace, memory_id, revision, memory_type, text, confidence,
            status, visibility, tenant_id, user_id, repo_id, authority_issuer,
            namespace_id, definition_id, source_session_id,
            source_event_start, source_event_end, source_commit_sha, superseded_by,
            expires_at, created_at, updated_at, creation_key, content_digest,
            provenance_digest
        ) VALUES ("""
        + ", ".join(["%s"] * 25)
        + ") RETURNING *",
        memory_values(namespace, entry),
    ).fetchone()
    assert row is not None
    return authority_from_row(row)  # type: ignore[return-value]


def _apply_mutation(
    connection: Any,
    namespace: str,
    mutation: GovernedMemoryLifecycleMutation,
    row: dict[str, Any],
    id_map: dict[str, MemoryId],
) -> GovernedMemoryEntry | GovernedMemoryTombstone:
    current = authority_from_row(row)
    if not isinstance(current, GovernedMemoryEntry):
        raise GovernedMemoryConflictError("Memory lifecycle target is deleted")
    if (
        current.revision != mutation.expected_revision
        or current.record.status != mutation.previous_status
    ):
        raise GovernedMemoryConflictError("Memory lifecycle revision or status changed")
    superseded = mutation.superseded_by
    if superseded is not None:
        superseded = id_map.get(str(superseded), superseded)
        row = connection.execute(
            """SELECT * FROM governed_memory_records
            WHERE deployment_namespace = %s AND memory_id = %s""",
            (namespace, superseded),
        ).fetchone()
        if row is None:
            raise GovernedMemoryConflictError("superseded_by Memory was not found")
        target = authority_from_row(row)
        if isinstance(target, GovernedMemoryTombstone):
            raise GovernedMemoryConflictError("superseded_by cannot target deleted Memory")
    record = current.record.model_copy(
        update={
            "status": mutation.status,
            "superseded_by": superseded,
            "updated_at": mutation.updated_at,
        }
    )
    return _replace_record(connection, namespace, record, current.revision)


def _replace_record(
    connection: Any, namespace: str, record: MemoryRecord, expected_revision: int
) -> GovernedMemoryEntry | GovernedMemoryTombstone:
    text = None if record.status is MemoryStatus.DELETED else record.text
    row = connection.execute(
        """
        UPDATE governed_memory_records
        SET revision = revision + 1, text = %s, status = %s, superseded_by = %s,
            updated_at = %s
        WHERE deployment_namespace = %s AND memory_id = %s AND revision = %s
          AND updated_at <= %s RETURNING *
        """,
        (
            text,
            record.status.value,
            record.superseded_by,
            record.updated_at,
            namespace,
            record.memory_id,
            expected_revision,
            record.updated_at,
        ),
    ).fetchone()
    if row is None:
        raise GovernedMemoryConflictError("Memory revision CAS failed")
    return authority_from_row(row)


def _append_events(
    connection: Any, namespace: str, events: tuple[SessionEvent, ...], expected: int
) -> tuple[SessionEvent, ...]:
    canonical = tuple(append_event_in_transaction(connection, namespace, event) for event in events)
    if tuple(event.sequence for event in canonical) != tuple(
        range(expected + 1, expected + 1 + len(events))
    ):
        raise GovernedMemoryConflictError("Memory Event range is not contiguous")
    return canonical


def _store_receipt(
    connection: Any,
    namespace: str,
    *,
    operation_id: str,
    operation_kind: GovernedMemoryOperationKind,
    request_digest: str,
    records: tuple[GovernedMemoryEntry | GovernedMemoryTombstone, ...],
    events: tuple[SessionEvent, ...],
    projection_revision: int,
) -> GovernedMemoryCommitResult:
    committed_at = connection.execute("SELECT transaction_timestamp() AS now").fetchone()["now"]
    final_records = {str(_memory_id(item)): item for item in records}
    receipt = GovernedMemoryOperationReceipt.create(
        operation_id=operation_id,
        operation_kind=operation_kind,
        request_digest=request_digest,
        memories=tuple(
            GovernedMemoryRevision(
                memory_id=_memory_id(entry),
                revision=entry.revision,
                status=_memory_status(entry),
            )
            for entry in sorted(final_records.values(), key=lambda item: str(_memory_id(item)))
        ),
        event_ids=tuple(event.event_id for event in events),
        event_sequences=tuple(event.sequence for event in events),
        anchor_event_start=events[0].sequence,
        anchor_event_end=events[-1].sequence,
        session_revision=events[-1].sequence,
        projection_revision=projection_revision,
        committed_at=committed_at,
    )
    connection.execute(
        """
        INSERT INTO governed_memory_operations (
            deployment_namespace, operation_id, operation_kind, request_digest,
            status, session_id, anchor_event_start, anchor_event_end,
            anchor_start_event_id, anchor_end_event_id, result_schema,
            result_json, result_digest, committed_at
        ) VALUES (%s, %s, %s, %s, 'committed', %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            namespace,
            operation_id,
            operation_kind.value,
            request_digest,
            events[0].session_id,
            receipt.anchor_event_start,
            receipt.anchor_event_end,
            events[0].event_id,
            events[-1].event_id,
            receipt.result_schema,
            Jsonb(receipt.model_dump(mode="json")),
            receipt.result_digest,
            receipt.committed_at,
        ),
    )
    return GovernedMemoryCommitResult(receipt=receipt)


def _enqueue_authority_delivery(
    connection: Any,
    namespace: str,
    scope: MemoryDeliveryScope | None,
    records: tuple[GovernedMemoryEntry | GovernedMemoryTombstone, ...],
) -> None:
    """Enqueue derived-index lifecycle changes inside the authority transaction."""

    if scope is None:
        return
    seen: set[tuple[MemoryId, int, MemoryDeliveryOperation]] = set()
    for entry in records:
        memory_id = _memory_id(entry)
        status = _memory_status(entry)
        operation = (
            MemoryDeliveryOperation.PUBLISH
            if status is MemoryStatus.CONFIRMED
            else MemoryDeliveryOperation.DELETE
            if status
            in {
                MemoryStatus.SUPERSEDED,
                MemoryStatus.EXPIRED,
                MemoryStatus.DELETED,
            }
            else None
        )
        if operation is None:
            continue
        identity = (memory_id, entry.revision, operation)
        if identity in seen:
            continue
        seen.add(identity)
        digest_row = connection.execute(
            """
            SELECT content_digest FROM governed_memory_records
            WHERE deployment_namespace = %s AND memory_id = %s
            """,
            (namespace, memory_id),
        ).fetchone()
        if digest_row is None:
            raise MemoryDeliveryConflictError("delivery authority row disappeared")
        operation_record = MemoryDeliveryOperationRecord(
            memory_id=memory_id,
            operation=operation,
            scope_digest=scope.scope_digest,
            generation=scope.generation,
            memory_revision=entry.revision,
            content_digest=digest_row["content_digest"],
            idempotency_key=(
                f"memory:{memory_id}:{scope.generation}:{entry.revision}:"
                f"{operation.value}:{scope.scope_digest}"
            ),
        )
        enqueue_in_transaction(connection, namespace, scope, operation_record)


def _operation_replay(
    connection: Any,
    namespace: str,
    operation_id: str,
    kind: GovernedMemoryOperationKind,
    request_digest: str,
    session_id: SessionId,
) -> GovernedMemoryCommitResult | None:
    return read_operation_receipt(
        connection,
        namespace,
        operation_id,
        kind=kind,
        session_id=session_id,
        request_digest=request_digest,
        lock=True,
    )


def _rewrite_event(event: SessionEvent, mapping: dict[str, str], *, sequence: int) -> SessionEvent:
    return event.model_copy(
        update={"sequence": sequence, "payload": _replace_ids(event.payload, mapping)}
    )


def _replace_ids(value: object, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_replace_ids(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _replace_ids(item, mapping) for key, item in value.items()}
    return value


def _scope_column(visibility: MemoryVisibility) -> str:
    return {
        MemoryVisibility.REPO: "repo_id",
        MemoryVisibility.USER: "user_id",
        MemoryVisibility.TENANT: "tenant_id",
    }[visibility]


def _scope_value(record: MemoryRecord) -> str:
    if record.authority_issuer is not None:
        return (
            f"{record.authority_issuer}|{record.namespace_id}|"
            f"{record.definition_id}"
        )
    value = {
        MemoryVisibility.REPO: record.repo_id,
        MemoryVisibility.USER: record.user_id,
        MemoryVisibility.TENANT: record.tenant_id,
    }[record.visibility]
    assert value is not None
    return value


def _scope_predicate(record: MemoryRecord) -> tuple[str, tuple[object, ...]]:
    if record.authority_issuer is not None:
        return (
            "authority_issuer = %s AND namespace_id = %s AND definition_id = %s",
            (
                record.authority_issuer,
                record.namespace_id,
                record.definition_id,
            ),
        )
    return (
        f"{_scope_column(record.visibility)} = %s",
        (_scope_value(record),),
    )


def _revision_for(rows: list[dict[str, Any]], memory_id: MemoryId) -> int:
    return int(next(row["revision"] for row in rows if row["memory_id"] == memory_id))


def _memory_id(entry: GovernedMemoryEntry | GovernedMemoryTombstone) -> MemoryId:
    return entry.record.memory_id if isinstance(entry, GovernedMemoryEntry) else entry.memory_id


def _memory_status(entry: GovernedMemoryEntry | GovernedMemoryTombstone) -> MemoryStatus:
    return entry.record.status if isinstance(entry, GovernedMemoryEntry) else entry.status
