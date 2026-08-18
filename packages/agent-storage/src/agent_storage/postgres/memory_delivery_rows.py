"""Typed views for PostgreSQL Memory delivery metadata."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memory_delivery import (
    MemoryDeliveryCertainty,
    MemoryDeliveryOperation,
    MemoryDeliveryOperationRecord,
    MemoryDeliveryScope,
    MemoryDeliveryScopeState,
    MemoryDeliveryState,
)


@dataclass(frozen=True, slots=True)
class MemoryDeliveryClaim:
    """A short-lived claim; the token is the only network-ack capability."""

    operation: MemoryDeliveryOperationRecord
    claim_token: str
    owner: str
    claim_expires_at: datetime
    provider_ref: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryProviderMapping:
    """A confirmed Memory-to-provider identity for one scope generation."""

    deployment_namespace: str
    memory_id: MemoryId
    scope_digest: str
    generation: int
    provider_ref: str
    memory_revision: int
    content_digest: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryDeliverySearchAdmission:
    """Authority metadata admitted after one batch mapping/revision check."""

    memory_id: MemoryId
    provider_ref: str
    memory_revision: int
    content_digest: str


def scope_from_row(row: dict[str, Any]) -> MemoryDeliveryScope:
    return MemoryDeliveryScope(
        deployment_namespace=row["deployment_namespace"],
        scope_digest=row["scope_digest"],
        generation=int(row["generation"]),
        state=MemoryDeliveryScopeState(row["state"]),
        revision=int(row["revision"]),
    )


def operation_from_row(row: dict[str, Any]) -> MemoryDeliveryOperationRecord:
    return MemoryDeliveryOperationRecord(
        memory_id=MemoryId(row["memory_id"]),
        operation=MemoryDeliveryOperation(row["operation"]),
        scope_digest=row["scope_digest"],
        generation=int(row["generation"]),
        memory_revision=int(row["memory_revision"]),
        content_digest=row["content_digest"],
        idempotency_key=row["idempotency_key"],
        state=MemoryDeliveryState(row["state"]),
        attempt=int(row["attempt"]),
        certainty=(None if row["certainty"] is None else MemoryDeliveryCertainty(row["certainty"])),
    )


def claim_from_row(row: dict[str, Any]) -> MemoryDeliveryClaim:
    claim_token = row.get("claim_token")
    owner = row.get("claim_owner")
    expires_at = row.get("claim_expires_at")
    if not isinstance(claim_token, str) or not isinstance(owner, str) or expires_at is None:
        raise ValueError("delivery claim row is missing its claim boundary")
    return MemoryDeliveryClaim(
        operation=operation_from_row(row),
        claim_token=claim_token,
        owner=owner,
        claim_expires_at=expires_at,
        provider_ref=row.get("provider_ref"),
        error_code=row.get("error_code"),
    )


def mapping_from_row(row: dict[str, Any]) -> MemoryProviderMapping:
    return MemoryProviderMapping(
        deployment_namespace=row["deployment_namespace"],
        memory_id=MemoryId(row["memory_id"]),
        scope_digest=row["scope_digest"],
        generation=int(row["generation"]),
        provider_ref=row["provider_ref"],
        memory_revision=int(row["memory_revision"]),
        content_digest=row["content_digest"],
        updated_at=row["updated_at"],
    )


def new_operation_record(
    memory_id: MemoryId,
    *,
    operation: MemoryDeliveryOperation,
    scope: MemoryDeliveryScope,
    memory_revision: int,
    content_digest: str,
    idempotency_key: str | None,
) -> MemoryDeliveryOperationRecord:
    key = idempotency_key or (
        f"memory:{memory_id}:{scope.generation}:{memory_revision}:"
        f"{operation.value}:{scope.scope_digest}"
    )
    return MemoryDeliveryOperationRecord(
        memory_id=memory_id,
        operation=operation,
        scope_digest=scope.scope_digest,
        generation=scope.generation,
        memory_revision=memory_revision,
        content_digest=content_digest,
        idempotency_key=key,
    )
