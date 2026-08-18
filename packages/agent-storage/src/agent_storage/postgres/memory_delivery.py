"""PostgreSQL v11 Memory delivery ledger; no provider or Memory text is stored."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta

from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memory_delivery import (
    MemoryDeliveryCertainty,
    MemoryDeliveryOperation,
    MemoryDeliveryOperationRecord,
    MemoryDeliveryScope,
    MemoryDeliveryState,
    MemoryDeliveryTransition,
)
from agent_core.ports.memory_delivery import MemoryDeliveryLedgerPort

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.memory_delivery_errors import MemoryDeliveryConflictError
from agent_storage.postgres.memory_delivery_rows import (
    MemoryDeliveryClaim,
    MemoryDeliverySearchAdmission,
    MemoryProviderMapping,
    mapping_from_row,
    new_operation_record,
    operation_from_row,
    scope_from_row,
)
from agent_storage.postgres.memory_delivery_scope import ensure_scope_in_transaction
from agent_storage.postgres.memory_delivery_search import revalidate_hits_in_transaction
from agent_storage.postgres.memory_delivery_transaction_support import (
    claim_next_in_transaction,
    complete_in_transaction,
    enqueue_in_transaction,
    reconcile_expired_in_flight,
    transition_in_transaction,
)


class PostgresMemoryDeliveryLedger(MemoryDeliveryLedgerPort):
    """Independent claim/CAS state for the derived provider index."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def ensure_scope(self, scope: MemoryDeliveryScope) -> MemoryDeliveryScope:
        with self._database.connect() as connection:
            return ensure_scope_in_transaction(connection, self._namespace, scope)

    def get_scope(self, *, scope_digest: str, generation: int) -> MemoryDeliveryScope | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM memory_delivery_scopes
                WHERE deployment_namespace = %s AND scope_digest = %s AND generation = %s
                """,
                (self._namespace, scope_digest, generation),
            ).fetchone()
        return None if row is None else scope_from_row(row)

    def enqueue(
        self,
        operation: MemoryDeliveryOperationRecord,
        *,
        scope: MemoryDeliveryScope,
    ) -> MemoryDeliveryOperationRecord:
        with self._database.connect() as connection:
            return enqueue_in_transaction(connection, self._namespace, scope, operation)

    def enqueue_publish(
        self,
        memory_id: MemoryId,
        *,
        memory_revision: int,
        content_digest: str,
        scope: MemoryDeliveryScope,
        idempotency_key: str | None = None,
    ) -> MemoryDeliveryOperationRecord:
        return self.enqueue(
            new_operation_record(
                memory_id,
                operation=MemoryDeliveryOperation.PUBLISH,
                scope=scope,
                memory_revision=memory_revision,
                content_digest=content_digest,
                idempotency_key=idempotency_key,
            ),
            scope=scope,
        )

    def enqueue_delete(
        self,
        memory_id: MemoryId,
        *,
        memory_revision: int,
        content_digest: str,
        scope: MemoryDeliveryScope,
        idempotency_key: str | None = None,
    ) -> MemoryDeliveryOperationRecord:
        return self.enqueue(
            new_operation_record(
                memory_id,
                operation=MemoryDeliveryOperation.DELETE,
                scope=scope,
                memory_revision=memory_revision,
                content_digest=content_digest,
                idempotency_key=idempotency_key,
            ),
            scope=scope,
        )

    def get(self, idempotency_key: str) -> MemoryDeliveryOperationRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM memory_delivery_operations
                WHERE deployment_namespace = %s AND idempotency_key = %s
                """,
                (self._namespace, idempotency_key.strip()),
            ).fetchone()
        return None if row is None else operation_from_row(row)

    def claim_next(
        self,
        *,
        owner: str,
        claim_ttl: timedelta = timedelta(seconds=60),
        scope: MemoryDeliveryScope | None = None,
    ) -> MemoryDeliveryClaim | None:
        with self._database.connect() as connection:
            return claim_next_in_transaction(
                connection,
                self._namespace,
                owner=owner,
                claim_ttl=claim_ttl,
                scope=scope,
            )

    def mark_in_flight(self, claim: MemoryDeliveryClaim) -> MemoryDeliveryClaim:
        request = MemoryDeliveryTransition(
            idempotency_key=claim.operation.idempotency_key,
            expected_state=MemoryDeliveryState.CLAIMED,
            next_state=MemoryDeliveryState.IN_FLIGHT,
            claim_token=claim.claim_token,
        )
        with self._database.connect() as connection:
            operation = transition_in_transaction(
                connection,
                self._namespace,
                request,
                owner=claim.owner,
            )
        return replace(claim, operation=operation)

    def complete(
        self,
        claim: MemoryDeliveryClaim,
        *,
        certainty: MemoryDeliveryCertainty,
        provider_ref: str | None = None,
        error_code: str | None = None,
    ) -> MemoryDeliveryOperationRecord:
        with self._database.connect() as connection:
            return complete_in_transaction(
                connection,
                self._namespace,
                claim,
                certainty=certainty,
                provider_ref=provider_ref,
                error_code=error_code,
            )

    def mark_uncertain(
        self,
        claim: MemoryDeliveryClaim,
        *,
        reason_code: str,
    ) -> MemoryDeliveryOperationRecord:
        request = MemoryDeliveryTransition(
            idempotency_key=claim.operation.idempotency_key,
            expected_state=MemoryDeliveryState.IN_FLIGHT,
            next_state=MemoryDeliveryState.UNCERTAIN,
            certainty=MemoryDeliveryCertainty.UNKNOWN,
            claim_token=claim.claim_token,
        )
        with self._database.connect() as connection:
            return transition_in_transaction(
                connection,
                self._namespace,
                request,
                error_code=reason_code,
                owner=claim.owner,
            )

    def requeue_no_effect(
        self,
        claim: MemoryDeliveryClaim,
    ) -> MemoryDeliveryOperationRecord:
        request = MemoryDeliveryTransition(
            idempotency_key=claim.operation.idempotency_key,
            expected_state=MemoryDeliveryState.IN_FLIGHT,
            next_state=MemoryDeliveryState.PENDING,
            certainty=MemoryDeliveryCertainty.DEFINITE_NO_EFFECT,
            claim_token=claim.claim_token,
        )
        with self._database.connect() as connection:
            return transition_in_transaction(
                connection,
                self._namespace,
                request,
                owner=claim.owner,
            )

    def mark_dead_letter(
        self,
        idempotency_key: str,
        *,
        reason_code: str,
    ) -> MemoryDeliveryOperationRecord:
        request = MemoryDeliveryTransition(
            idempotency_key=idempotency_key,
            expected_state=MemoryDeliveryState.PENDING,
            next_state=MemoryDeliveryState.DEAD_LETTER,
            certainty=MemoryDeliveryCertainty.DEFINITE_NO_EFFECT,
        )
        with self._database.connect() as connection:
            return transition_in_transaction(
                connection,
                self._namespace,
                request,
                error_code=reason_code,
            )

    def reconcile_expired(
        self,
        *,
        limit: int = 100,
        scope: MemoryDeliveryScope | None = None,
    ) -> tuple[MemoryDeliveryOperationRecord, ...]:
        with self._database.connect() as connection:
            return reconcile_expired_in_flight(
                connection,
                self._namespace,
                limit=limit,
                scope=scope,
            )

    def get_mapping(
        self,
        memory_id: MemoryId,
        *,
        scope: MemoryDeliveryScope,
    ) -> MemoryProviderMapping | None:
        if scope.deployment_namespace != self._namespace:
            raise MemoryDeliveryConflictError("delivery scope namespace does not match database")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM memory_provider_mappings
                WHERE deployment_namespace = %s AND scope_digest = %s
                  AND generation = %s AND memory_id = %s
                """,
                (self._namespace, scope.scope_digest, scope.generation, memory_id),
            ).fetchone()
        return None if row is None else mapping_from_row(row)

    def revalidate_search_hits(
        self,
        scope: MemoryDeliveryScope,
        hits: Iterable[tuple[MemoryId, str]],
    ) -> tuple[MemoryDeliverySearchAdmission, ...]:
        with self._database.connect() as connection:
            return revalidate_hits_in_transaction(connection, self._namespace, scope, hits)

    def transition(self, request: MemoryDeliveryTransition) -> MemoryDeliveryOperationRecord:
        with self._database.connect() as connection:
            return transition_in_transaction(connection, self._namespace, request)

    def quarantine_scope(
        self,
        scope: MemoryDeliveryScope,
        *,
        reason_code: str,
    ) -> MemoryDeliveryScope:
        reason_code = reason_code.strip()
        if not reason_code or len(reason_code) > 128:
            raise ValueError("quarantine reason code must be non-blank and bounded")
        with self._database.connect() as connection:
            row = connection.execute(
                """
                UPDATE memory_delivery_scopes
                SET state = 'quarantined', revision = revision + 1,
                    reason_code = %s, updated_at = transaction_timestamp()
                WHERE deployment_namespace = %s AND scope_digest = %s AND generation = %s
                  AND revision = %s
                RETURNING *
                """,
                (
                    reason_code,
                    self._namespace,
                    scope.scope_digest,
                    scope.generation,
                    scope.revision,
                ),
            ).fetchone()
            if row is None:
                raise MemoryDeliveryConflictError("delivery scope quarantine CAS failed")
            return scope_from_row(row)

    @property
    def _namespace(self) -> str:
        return self._database.deployment_namespace


__all__ = [
    "MemoryDeliveryClaim",
    "MemoryDeliveryConflictError",
    "MemoryDeliverySearchAdmission",
    "MemoryProviderMapping",
    "PostgresMemoryDeliveryLedger",
    "PostgresMemoryDeliveryStore",
]


PostgresMemoryDeliveryStore = PostgresMemoryDeliveryLedger
