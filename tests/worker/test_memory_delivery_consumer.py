from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    GovernedMemoryTombstone,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility
from agent_core.domain.memory_delivery import (
    MemoryDeliveryCertainty,
    MemoryDeliveryOperation,
    MemoryDeliveryOperationRecord,
    MemoryDeliveryScope,
    MemoryDeliveryState,
)
from agent_core.ports.agent_memory_gateway import (
    MemoryGatewayMutationResult,
    MemoryGatewayStatus,
)
from agent_storage.postgres.memory_delivery_rows import MemoryDeliveryClaim
from zebra_agent_worker.memory_delivery_consumer import GovernedMemoryDeliveryConsumer

NOW = datetime.now(UTC)


class _Ledger:
    deployment_namespace = "cloud-a"

    def __init__(self, claim: MemoryDeliveryClaim) -> None:
        self.claim = claim
        self.completed: tuple[MemoryDeliveryCertainty, str | None] | None = None
        self.uncertain: str | None = None
        self.requeued = False

    def claim_next(self, **kwargs):  # noqa: ANN003, ANN201
        del kwargs
        claim, self.claim = self.claim, None
        return claim

    def mark_in_flight(self, claim):  # noqa: ANN001, ANN201
        return replace(
            claim,
            operation=claim.operation.transition(MemoryDeliveryState.IN_FLIGHT),
        )

    def complete(self, claim, *, certainty, provider_ref=None, error_code=None):  # noqa: ANN001
        del claim, provider_ref
        self.completed = (certainty, error_code)

    def mark_uncertain(self, claim, *, reason_code):  # noqa: ANN001
        del claim
        self.uncertain = reason_code

    def requeue_no_effect(self, claim):  # noqa: ANN001
        del claim
        self.requeued = True


class _Authority:
    def __init__(self, value) -> None:  # noqa: ANN001
        self.value = value

    def get_authority(self, memory_id, *, management):  # noqa: ANN001, ANN201
        del memory_id, management
        return self.value


class _Gateway:
    def __init__(self, outcome: MemoryGatewayMutationResult) -> None:
        self.outcome = outcome
        self.published = 0
        self.deleted = 0

    def publish(self, publication):  # noqa: ANN001, ANN201
        del publication
        self.published += 1
        return self.outcome

    def delete(self, request):  # noqa: ANN001, ANN201
        del request
        self.deleted += 1
        return self.outcome


def test_confirmed_revision_is_published_and_settled() -> None:
    entry = _entry()
    ledger = _Ledger(_claim(entry, operation=MemoryDeliveryOperation.PUBLISH))
    gateway = _Gateway(
        MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            provider_ref="provider-1",
        )
    )

    result = _consumer(ledger, entry, gateway).consume_once()

    assert result.status == "completed"
    assert gateway.published == 1
    assert ledger.completed == (MemoryDeliveryCertainty.APPLIED, None)


def test_tombstone_prevents_stale_publish_without_provider_call() -> None:
    entry = _entry()
    tombstone = GovernedMemoryTombstone(
        deployment_namespace="cloud-a",
        memory_id=entry.record.memory_id,
        revision=entry.revision + 1,
        memory_type=entry.record.memory_type,
        visibility=entry.record.visibility,
        repo_id=entry.record.repo_id,
        provenance_digest="a" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    ledger = _Ledger(_claim(entry, operation=MemoryDeliveryOperation.PUBLISH))
    gateway = _Gateway(MemoryGatewayMutationResult(status=MemoryGatewayStatus.DISABLED))

    result = _consumer(ledger, tombstone, gateway).consume_once()

    assert result.reason == "authority_superseded"
    assert gateway.published == 0
    assert ledger.completed == (
        MemoryDeliveryCertainty.DEFINITE_NO_EFFECT,
        "authority_superseded",
    )


def test_unknown_provider_result_is_quarantined_not_retried() -> None:
    entry = _entry()
    ledger = _Ledger(_claim(entry, operation=MemoryDeliveryOperation.PUBLISH))
    gateway = _Gateway(
        MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.DEGRADED,
            detail="response lost",
        )
    )

    result = _consumer(ledger, entry, gateway).consume_once()

    assert result.status == "uncertain"
    assert ledger.uncertain == "response_lost"
    assert ledger.completed is None


def test_newer_confirmed_revision_prevents_stale_delete() -> None:
    entry = _entry()
    stale_delete = _claim(entry, operation=MemoryDeliveryOperation.DELETE)
    newer = entry.model_copy(update={"revision": entry.revision + 1})
    ledger = _Ledger(stale_delete)
    gateway = _Gateway(
        MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            provider_ref="provider-1",
        )
    )

    result = _consumer(ledger, newer, gateway).consume_once()

    assert result.reason == "authority_superseded"
    assert gateway.deleted == 0
    assert ledger.completed == (
        MemoryDeliveryCertainty.DEFINITE_NO_EFFECT,
        "authority_superseded",
    )


def test_disabled_provider_leaves_operation_pending() -> None:
    entry = _entry()
    ledger = _Ledger(_claim(entry, operation=MemoryDeliveryOperation.PUBLISH))
    gateway = _Gateway(MemoryGatewayMutationResult(status=MemoryGatewayStatus.DISABLED))

    result = _consumer(ledger, entry, gateway).consume_once()

    assert result.status == "deferred"
    assert ledger.requeued


def _consumer(ledger: _Ledger, authority, gateway: _Gateway):  # noqa: ANN001, ANN201
    return GovernedMemoryDeliveryConsumer(
        ledger=ledger,  # type: ignore[arg-type]
        authority=_Authority(authority),  # type: ignore[arg-type]
        gateway=gateway,
        scope=MemoryDeliveryScope(
            deployment_namespace="cloud-a",
            scope_digest="b" * 64,
            generation=1,
            revision=0,
        ),
        owner="worker-a",
        claim_ttl=timedelta(seconds=30),
    )


def _entry() -> GovernedMemoryEntry:
    record = MemoryRecord(
        memory_id=MemoryId(uuid4()),
        memory_type=MemoryType.PROCEDURE,
        text="Run the verified deployment check.",
        confidence=1,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra",
        created_at=NOW,
        updated_at=NOW,
    )
    return GovernedMemoryEntry(
        deployment_namespace="cloud-a",
        record=record,
        revision=2,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=canonical_governed_memory_content_hash(record),
    )


def _claim(
    entry: GovernedMemoryEntry,
    *,
    operation: MemoryDeliveryOperation,
) -> MemoryDeliveryClaim:
    return MemoryDeliveryClaim(
        operation=MemoryDeliveryOperationRecord(
            memory_id=entry.record.memory_id,
            operation=operation,
            scope_digest="b" * 64,
            generation=1,
            memory_revision=entry.revision,
            content_digest=entry.content_digest,
            idempotency_key="memory-operation-1",
            state=MemoryDeliveryState.CLAIMED,
            attempt=1,
        ),
        claim_token="claim-token",
        owner="worker-a",
        claim_expires_at=NOW + timedelta(minutes=1),
    )
