"""Provider-neutral governed Memory delivery with authority revalidation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    GovernedMemoryManagementContext,
    GovernedMemoryTombstone,
)
from agent_core.domain.memories import MemoryStatus
from agent_core.domain.memory_delivery import (
    MemoryDeliveryCertainty,
    MemoryDeliveryOperation,
    MemoryDeliveryScope,
)
from agent_core.ports.agent_memory_gateway import (
    AgentMemoryGatewayPort,
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewayMutationResult,
    MemoryGatewayStatus,
)
from agent_core.ports.governed_memory_store import GovernedMemoryStorePort
from agent_storage.postgres.memory_delivery import PostgresMemoryDeliveryLedger
from agent_storage.postgres.memory_delivery_rows import MemoryDeliveryClaim


@dataclass(frozen=True, slots=True)
class MemoryDeliveryConsumption:
    idempotency_key: str | None
    status: str
    reason: str | None = None


class GovernedMemoryDeliveryConsumer:
    """Deliver one ordered mutation without making the provider authoritative."""

    def __init__(
        self,
        *,
        ledger: PostgresMemoryDeliveryLedger,
        authority: GovernedMemoryStorePort,
        gateway: AgentMemoryGatewayPort,
        scope: MemoryDeliveryScope,
        owner: str,
        claim_ttl: timedelta = timedelta(seconds=60),
    ) -> None:
        if ledger.deployment_namespace != scope.deployment_namespace:
            raise ValueError("Memory delivery scope must match the ledger namespace")
        self._ledger = ledger
        self._authority = authority
        self._gateway = gateway
        self._scope = scope
        self._owner = owner.strip()
        self._claim_ttl = claim_ttl
        if not self._owner:
            raise ValueError("Memory delivery owner must not be blank")

    def consume_once(self) -> MemoryDeliveryConsumption:
        claim = self._ledger.claim_next(
            owner=self._owner,
            claim_ttl=self._claim_ttl,
            scope=self._scope,
        )
        if claim is None:
            return MemoryDeliveryConsumption(idempotency_key=None, status="idle")
        try:
            governed = self._authority.get_authority(
                claim.operation.memory_id,
                management=GovernedMemoryManagementContext(
                    operation_id=claim.operation.idempotency_key,
                    operator=self._owner,
                    reason="deliver governed Memory lifecycle to derived index",
                ),
            )
        except Exception:
            # No provider boundary was crossed. The short claim may safely expire
            # and return to pending through the existing ledger reconciliation.
            return _result(claim, "deferred", "authority_unavailable")
        if not _authority_allows(claim, governed):
            return self._complete_without_provider(claim, reason="authority_superseded")
        in_flight = self._ledger.mark_in_flight(claim)
        try:
            outcome = self._mutate_provider(in_flight, governed)
        except Exception:
            self._ledger.mark_uncertain(in_flight, reason_code="provider_exception")
            return _result(claim, "uncertain", "provider_exception")
        return self._settle(in_flight, outcome)

    def _complete_without_provider(
        self,
        claim: MemoryDeliveryClaim,
        *,
        reason: str,
    ) -> MemoryDeliveryConsumption:
        in_flight = self._ledger.mark_in_flight(claim)
        self._ledger.complete(
            in_flight,
            certainty=MemoryDeliveryCertainty.DEFINITE_NO_EFFECT,
            error_code=reason,
        )
        return _result(claim, "completed", reason)

    def _mutate_provider(
        self,
        claim: MemoryDeliveryClaim,
        governed: GovernedMemoryEntry | GovernedMemoryTombstone | None,
    ) -> MemoryGatewayMutationResult:
        namespace = f"{self._scope.scope_digest}:{self._scope.generation}"
        if claim.operation.operation is MemoryDeliveryOperation.PUBLISH:
            assert isinstance(governed, GovernedMemoryEntry)
            return self._gateway.publish(
                ConfirmedMemoryPublication(
                    memory_id=governed.record.memory_id,
                    namespace=namespace,
                    text=governed.record.text,
                    idempotency_key=claim.operation.idempotency_key,
                )
            )
        return self._gateway.delete(
            MemoryGatewayDeleteRequest(
                memory_id=claim.operation.memory_id,
                namespace=namespace,
                idempotency_key=claim.operation.idempotency_key,
            )
        )

    def _settle(
        self,
        claim: MemoryDeliveryClaim,
        outcome: MemoryGatewayMutationResult,
    ) -> MemoryDeliveryConsumption:
        certainty = outcome.certainty
        assert certainty is not None
        if outcome.status is MemoryGatewayStatus.DISABLED:
            self._ledger.requeue_no_effect(claim)
            return _result(claim, "deferred", "provider_disabled")
        if certainty is MemoryDeliveryCertainty.UNKNOWN:
            reason = _reason_code(outcome.detail, "provider_unknown") or "provider_unknown"
            self._ledger.mark_uncertain(
                claim,
                reason_code=reason,
            )
            return _result(claim, "uncertain", outcome.detail)
        self._ledger.complete(
            claim,
            certainty=certainty,
            provider_ref=outcome.provider_ref,
            error_code=_reason_code(outcome.detail, None),
        )
        return _result(claim, "completed", outcome.detail)


def _authority_allows(
    claim: MemoryDeliveryClaim,
    governed: GovernedMemoryEntry | GovernedMemoryTombstone | None,
) -> bool:
    operation = claim.operation
    if operation.operation is MemoryDeliveryOperation.PUBLISH:
        return (
            isinstance(governed, GovernedMemoryEntry)
            and governed.revision == operation.memory_revision
            and governed.content_digest == operation.content_digest
            and governed.record.status is MemoryStatus.CONFIRMED
            and (
                governed.record.expires_at is None
                or governed.record.expires_at > datetime.now(UTC)
            )
        )
    if isinstance(governed, GovernedMemoryTombstone):
        return governed.revision >= operation.memory_revision
    return (
        isinstance(governed, GovernedMemoryEntry)
        and governed.revision >= operation.memory_revision
        and governed.record.status in {MemoryStatus.SUPERSEDED, MemoryStatus.EXPIRED}
    )


def _reason_code(detail: str | None, default: str | None) -> str | None:
    if detail is None:
        return default
    normalized = "".join(character if character.isalnum() else "_" for character in detail)
    return normalized.strip("_")[:128] or default


def _result(
    claim: MemoryDeliveryClaim,
    status: str,
    reason: str | None,
) -> MemoryDeliveryConsumption:
    return MemoryDeliveryConsumption(
        idempotency_key=claim.operation.idempotency_key,
        status=status,
        reason=reason,
    )
