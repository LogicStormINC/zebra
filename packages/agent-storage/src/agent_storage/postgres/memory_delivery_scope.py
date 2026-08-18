"""Scope-generation lifecycle transactions for Memory delivery."""

from typing import Any

from agent_core.domain.memory_delivery import (
    MemoryDeliveryScope,
    MemoryDeliveryScopeState,
)

from agent_storage.postgres.memory_delivery_errors import MemoryDeliveryConflictError
from agent_storage.postgres.memory_delivery_rows import scope_from_row


def ensure_scope_in_transaction(
    connection: Any,
    namespace: str,
    scope: MemoryDeliveryScope,
    *,
    require_active: bool = True,
) -> MemoryDeliveryScope:
    _require_namespace(namespace, scope)
    if require_active and scope.state is not MemoryDeliveryScopeState.ACTIVE:
        raise MemoryDeliveryConflictError("delivery scope is not active")
    row = connection.execute(
        """
        SELECT * FROM memory_delivery_scopes
        WHERE deployment_namespace = %s AND scope_digest = %s AND generation = %s
        FOR UPDATE
        """,
        (namespace, scope.scope_digest, scope.generation),
    ).fetchone()
    if row is None:
        if scope.state is MemoryDeliveryScopeState.ACTIVE:
            active = connection.execute(
                """
                SELECT scope_digest, generation FROM memory_delivery_scopes
                WHERE deployment_namespace = %s AND scope_digest = %s
                  AND state = 'active'
                FOR UPDATE
                """,
                (namespace, scope.scope_digest),
            ).fetchone()
            if active is not None:
                raise MemoryDeliveryConflictError("another delivery scope generation is active")
        inserted = connection.execute(
            """
            INSERT INTO memory_delivery_scopes (
                deployment_namespace, scope_digest, generation, state, revision
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                namespace,
                scope.scope_digest,
                scope.generation,
                scope.state.value,
                scope.revision,
            ),
        ).fetchone()
        assert inserted is not None
        return scope_from_row(inserted)
    current = scope_from_row(row)
    if require_active and current.state is not MemoryDeliveryScopeState.ACTIVE:
        raise MemoryDeliveryConflictError("delivery scope is not active")
    if current.revision > scope.revision:
        raise MemoryDeliveryConflictError("delivery scope revision is stale")
    if current.revision == scope.revision:
        if current.state is not scope.state:
            raise MemoryDeliveryConflictError("delivery scope state changed")
        return current
    if scope.state is MemoryDeliveryScopeState.ACTIVE:
        active = connection.execute(
            """
            SELECT scope_digest, generation FROM memory_delivery_scopes
            WHERE deployment_namespace = %s AND state = 'active'
              AND scope_digest = %s
              AND NOT (scope_digest = %s AND generation = %s)
            FOR UPDATE
            """,
            (namespace, scope.scope_digest, scope.scope_digest, scope.generation),
        ).fetchone()
        if active is not None:
            raise MemoryDeliveryConflictError("another delivery scope generation is active")
    updated = connection.execute(
        """
        UPDATE memory_delivery_scopes
        SET state = %s, revision = %s, reason_code = NULL,
            updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND scope_digest = %s AND generation = %s
          AND revision = %s
        RETURNING *
        """,
        (
            scope.state.value,
            scope.revision,
            namespace,
            scope.scope_digest,
            scope.generation,
            current.revision,
        ),
    ).fetchone()
    if updated is None:
        raise MemoryDeliveryConflictError("delivery scope CAS failed")
    return scope_from_row(updated)


def quarantine_scope_for_operation(
    connection: Any,
    namespace: str,
    operation_row: dict[str, Any],
    reason_code: str,
) -> None:
    reason_code = _required_text(reason_code, "quarantine reason", maximum=128)
    connection.execute(
        """
        UPDATE memory_delivery_scopes
        SET state = 'quarantined', revision = revision + 1,
            reason_code = %s, updated_at = transaction_timestamp()
        WHERE deployment_namespace = %s AND scope_digest = %s AND generation = %s
          AND state <> 'quarantined'
        """,
        (
            reason_code,
            namespace,
            operation_row["scope_digest"],
            operation_row["generation"],
        ),
    )


def _require_namespace(namespace: str, scope: MemoryDeliveryScope) -> None:
    if namespace != scope.deployment_namespace:
        raise MemoryDeliveryConflictError("delivery scope namespace does not match database")


def _required_text(value: str, label: str, *, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} must be non-blank and bounded")
    return normalized
