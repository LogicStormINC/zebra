"""Small SQL transactions for the PostgreSQL Memory delivery ledger."""

from datetime import timedelta
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from agent_core.domain.memory_delivery import (
    MemoryDeliveryCertainty,
    MemoryDeliveryOperation,
    MemoryDeliveryOperationRecord,
    MemoryDeliveryScope,
    MemoryDeliveryScopeState,
    MemoryDeliveryState,
    validate_memory_delivery_transition,
)

from agent_storage.postgres.memory_delivery_errors import MemoryDeliveryConflictError
from agent_storage.postgres.memory_delivery_rows import (
    MemoryDeliveryClaim,
    claim_from_row,
    operation_from_row,
)
from agent_storage.postgres.memory_delivery_scope import (
    ensure_scope_in_transaction,
    quarantine_scope_for_operation,
)


def enqueue_in_transaction(
    connection: Any,
    namespace: str,
    scope: MemoryDeliveryScope,
    operation: MemoryDeliveryOperationRecord,
) -> MemoryDeliveryOperationRecord:
    _require_namespace(namespace, scope)
    if operation.scope_digest != scope.scope_digest or operation.generation != scope.generation:
        raise MemoryDeliveryConflictError("delivery operation scope does not match")
    if operation.state is not MemoryDeliveryState.PENDING or operation.attempt != 0:
        raise MemoryDeliveryConflictError("new delivery operation must be pending")
    if operation.certainty is not None:
        raise MemoryDeliveryConflictError("new delivery operation cannot carry certainty")
    ensure_scope_in_transaction(connection, namespace, scope)
    existing = connection.execute(
        """
        SELECT * FROM memory_delivery_operations
        WHERE deployment_namespace = %s AND idempotency_key = %s FOR UPDATE
        """,
        (namespace, operation.idempotency_key),
    ).fetchone()
    if existing is not None:
        stored = operation_from_row(existing)
        if not _same_operation_identity(stored, operation):
            raise MemoryDeliveryConflictError("delivery idempotency key was reused")
        return stored
    inserted = connection.execute(
        """
        INSERT INTO memory_delivery_operations (
            deployment_namespace, delivery_operation_id, memory_id,
            scope_digest, generation, memory_revision, content_digest, operation,
            idempotency_key, state, attempt
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', 0)
        RETURNING *
        """,
        (
            namespace,
            uuid4(),
            operation.memory_id,
            operation.scope_digest,
            operation.generation,
            operation.memory_revision,
            operation.content_digest,
            operation.operation.value,
            operation.idempotency_key,
        ),
    ).fetchone()
    assert inserted is not None
    return operation_from_row(inserted)


def claim_next_in_transaction(
    connection: Any,
    namespace: str,
    *,
    owner: str,
    claim_ttl: timedelta,
    scope: MemoryDeliveryScope | None = None,
) -> MemoryDeliveryClaim | None:
    owner = _required_text(owner, "claim owner", maximum=255)
    if claim_ttl <= timedelta(0):
        raise ValueError("delivery claim TTL must be positive")
    params: list[object] = [namespace]
    scope_clause = ""
    if scope is not None:
        _require_namespace(namespace, scope)
        if scope.state is not MemoryDeliveryScopeState.ACTIVE:
            raise MemoryDeliveryConflictError("delivery scope is not active")
        scope_clause = (
            " AND operation.scope_digest = %s AND operation.generation = %s AND scope.revision = %s"
        )
        params.extend((scope.scope_digest, scope.generation, scope.revision))
    token = token_urlsafe(32)
    params.extend((token, owner, claim_ttl, namespace))
    row = connection.execute(
        f"""
        WITH candidate AS (
            SELECT operation.delivery_operation_id
            FROM memory_delivery_operations operation
            JOIN memory_delivery_scopes scope
              ON scope.deployment_namespace = operation.deployment_namespace
             AND scope.scope_digest = operation.scope_digest
             AND scope.generation = operation.generation
            WHERE operation.deployment_namespace = %s
              AND scope.state = 'active'
              {scope_clause}
              AND (
                  (operation.state = 'pending'
                   AND operation.next_attempt_at <= transaction_timestamp())
                  OR (operation.state = 'claimed'
                      AND operation.claim_expires_at <= transaction_timestamp())
              )
            ORDER BY operation.next_attempt_at, operation.created_at,
                     operation.delivery_operation_id
            FOR UPDATE OF operation SKIP LOCKED
            LIMIT 1
        )
        UPDATE memory_delivery_operations operation
        SET state = 'claimed', attempt = operation.attempt + 1,
            claim_token = %s, claim_owner = %s,
            claim_expires_at = transaction_timestamp() + %s::interval,
            certainty = NULL, updated_at = transaction_timestamp()
        FROM candidate
        WHERE operation.deployment_namespace = %s
          AND operation.delivery_operation_id = candidate.delivery_operation_id
        RETURNING operation.*
        """,
        params,
    ).fetchone()
    return None if row is None else claim_from_row(row)


def transition_in_transaction(
    connection: Any,
    namespace: str,
    request: Any,
    *,
    provider_ref: str | None = None,
    error_code: str | None = None,
    owner: str | None = None,
) -> MemoryDeliveryOperationRecord:
    validate_memory_delivery_transition(
        request.expected_state,
        request.next_state,
        certainty=request.certainty,
    )
    _require_transition_claim(request.expected_state, request.claim_token)
    if owner is not None:
        owner = _required_text(owner, "claim owner", maximum=255)
    if error_code is not None:
        error_code = _required_text(error_code, "delivery error code", maximum=128)
    where = [
        "deployment_namespace = %s",
        "idempotency_key = %s",
        "state = %s",
    ]
    where_params: list[object] = [
        namespace,
        request.idempotency_key,
        request.expected_state.value,
    ]
    if request.claim_token is not None:
        where.extend(("claim_token = %s", "claim_expires_at > transaction_timestamp()"))
        where_params.append(request.claim_token)
    if owner is not None:
        where.append("claim_owner = %s")
        where_params.append(owner)
    clear_claim = request.next_state not in {
        MemoryDeliveryState.CLAIMED,
        MemoryDeliveryState.IN_FLIGHT,
    }
    updated = connection.execute(
        f"""
        UPDATE memory_delivery_operations
        SET state = %s, certainty = %s,
            provider_ref = COALESCE(%s, provider_ref), error_code = %s,
            claim_token = CASE WHEN %s THEN NULL ELSE claim_token END,
            claim_owner = CASE WHEN %s THEN NULL ELSE claim_owner END,
            claim_expires_at = CASE WHEN %s THEN NULL ELSE claim_expires_at END,
            next_attempt_at = CASE WHEN %s THEN transaction_timestamp()
                                   ELSE next_attempt_at END,
            completed_at = CASE WHEN %s THEN transaction_timestamp()
                               ELSE completed_at END,
            updated_at = transaction_timestamp()
        WHERE {" AND ".join(where)}
        RETURNING *
        """,
        # Repeat the clear/completed flags for each CASE expression deliberately;
        # keeping the SQL explicit prevents a hidden client-time boundary.
        [
            request.next_state.value,
            request.certainty.value if request.certainty is not None else None,
            provider_ref,
            error_code,
            clear_claim,
            clear_claim,
            clear_claim,
            request.next_state is MemoryDeliveryState.PENDING,
            request.next_state is MemoryDeliveryState.COMPLETED,
            *where_params,
        ],
    ).fetchone()
    if updated is None:
        raise MemoryDeliveryConflictError("delivery transition CAS failed")
    if request.next_state is MemoryDeliveryState.UNCERTAIN:
        quarantine_scope_for_operation(connection, namespace, updated, error_code or "unknown")
    return operation_from_row(updated)


def complete_in_transaction(
    connection: Any,
    namespace: str,
    claim: MemoryDeliveryClaim,
    *,
    certainty: MemoryDeliveryCertainty,
    provider_ref: str | None = None,
    error_code: str | None = None,
) -> MemoryDeliveryOperationRecord:
    if certainty not in {
        MemoryDeliveryCertainty.APPLIED,
        MemoryDeliveryCertainty.DEFINITE_NO_EFFECT,
    }:
        raise ValueError("completed delivery requires applied or definite_no_effect")
    if claim.operation.state not in {
        MemoryDeliveryState.CLAIMED,
        MemoryDeliveryState.IN_FLIGHT,
    }:
        raise MemoryDeliveryConflictError("only claimed delivery can complete")
    if (
        claim.operation.operation is MemoryDeliveryOperation.PUBLISH
        and (certainty is MemoryDeliveryCertainty.APPLIED)
        and not provider_ref
    ):
        raise ValueError("applied publish requires provider_ref")
    request = _transition_request(
        claim.operation.idempotency_key,
        MemoryDeliveryState.IN_FLIGHT,
        MemoryDeliveryState.COMPLETED,
        certainty,
        claim.claim_token,
    )
    operation = transition_in_transaction(
        connection,
        namespace,
        request,
        provider_ref=provider_ref,
        error_code=error_code,
        owner=claim.owner,
    )
    if (
        certainty is MemoryDeliveryCertainty.APPLIED
        and operation.operation is MemoryDeliveryOperation.PUBLISH
    ):
        _upsert_mapping(connection, namespace, operation, provider_ref)
    elif operation.operation is MemoryDeliveryOperation.DELETE:
        _delete_mapping(connection, namespace, operation)
    return operation


def reconcile_expired_in_flight(
    connection: Any,
    namespace: str,
    *,
    limit: int = 100,
    scope: MemoryDeliveryScope | None = None,
) -> tuple[MemoryDeliveryOperationRecord, ...]:
    if limit < 1 or limit > 1000:
        raise ValueError("delivery reconciliation limit must be between 1 and 1000")
    params: list[object] = [namespace]
    clause = ""
    if scope is not None:
        _require_namespace(namespace, scope)
        clause = " AND scope_digest = %s AND generation = %s"
        params.extend((scope.scope_digest, scope.generation))
    params.append(limit)
    rows = connection.execute(
        f"""
        WITH expired AS (
            SELECT deployment_namespace, delivery_operation_id
            FROM memory_delivery_operations
            WHERE deployment_namespace = %s AND state = 'in_flight'
              AND claim_expires_at <= transaction_timestamp(){clause}
            ORDER BY claim_expires_at, delivery_operation_id
            FOR UPDATE SKIP LOCKED LIMIT %s
        )
        UPDATE memory_delivery_operations operation
        SET state = 'uncertain', certainty = 'unknown',
            claim_token = NULL, claim_owner = NULL, claim_expires_at = NULL,
            error_code = 'claim_expired', updated_at = transaction_timestamp()
        FROM expired
        WHERE operation.deployment_namespace = expired.deployment_namespace
          AND operation.delivery_operation_id = expired.delivery_operation_id
        RETURNING operation.*
        """,
        params,
    ).fetchall()
    for row in rows:
        quarantine_scope_for_operation(connection, namespace, row, "claim_expired")
    return tuple(operation_from_row(row) for row in rows)


def _upsert_mapping(
    connection: Any,
    namespace: str,
    operation: MemoryDeliveryOperationRecord,
    provider_ref: str | None,
) -> None:
    if not provider_ref:
        raise ValueError("mapping requires provider_ref")
    connection.execute(
        """
        INSERT INTO memory_provider_mappings (
            deployment_namespace, scope_digest, generation, memory_id,
            provider_ref, memory_revision, content_digest
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (deployment_namespace, scope_digest, generation, memory_id)
        DO UPDATE SET provider_ref = EXCLUDED.provider_ref,
                      memory_revision = EXCLUDED.memory_revision,
                      content_digest = EXCLUDED.content_digest,
                      updated_at = transaction_timestamp()
        WHERE memory_provider_mappings.memory_revision <= EXCLUDED.memory_revision
        """,
        (
            namespace,
            operation.scope_digest,
            operation.generation,
            operation.memory_id,
            provider_ref,
            operation.memory_revision,
            operation.content_digest,
        ),
    )


def _delete_mapping(
    connection: Any,
    namespace: str,
    operation: MemoryDeliveryOperationRecord,
) -> None:
    connection.execute(
        """
        DELETE FROM memory_provider_mappings
        WHERE deployment_namespace = %s AND scope_digest = %s AND generation = %s
          AND memory_id = %s AND memory_revision <= %s
        """,
        (
            namespace,
            operation.scope_digest,
            operation.generation,
            operation.memory_id,
            operation.memory_revision,
        ),
    )


def _transition_request(
    key: str,
    expected: MemoryDeliveryState,
    target: MemoryDeliveryState,
    certainty: MemoryDeliveryCertainty | None,
    token: str,
) -> Any:
    from agent_core.domain.memory_delivery import MemoryDeliveryTransition

    return MemoryDeliveryTransition(
        idempotency_key=key,
        expected_state=expected,
        next_state=target,
        certainty=certainty,
        claim_token=token,
    )


def _same_operation_identity(
    left: MemoryDeliveryOperationRecord, right: MemoryDeliveryOperationRecord
) -> bool:
    return (
        left.memory_id == right.memory_id
        and left.operation is right.operation
        and left.scope_digest == right.scope_digest
        and left.generation == right.generation
        and left.memory_revision == right.memory_revision
        and left.content_digest == right.content_digest
    )


def _require_transition_claim(state: MemoryDeliveryState, token: str | None) -> None:
    if state in {MemoryDeliveryState.CLAIMED, MemoryDeliveryState.IN_FLIGHT} and not token:
        raise ValueError("claimed delivery transitions require claim_token")


def _require_namespace(namespace: str, scope: MemoryDeliveryScope) -> None:
    if namespace != scope.deployment_namespace:
        raise MemoryDeliveryConflictError("delivery scope namespace does not match database")


def _required_text(value: str, label: str, *, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} must be non-blank and bounded")
    return normalized
