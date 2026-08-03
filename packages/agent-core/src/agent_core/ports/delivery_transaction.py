"""Port for cloud delivery ownership and atomic completion."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agent_core.domain.delivery_audit import DeliveryAuditRecord
from agent_core.domain.delivery_transaction import (
    DeliveryTransactionRecord,
)
from agent_core.ports.idempotency_store import IdempotencyRecord


class DeliveryClaimResultType(StrEnum):
    CLAIMED = "claimed"
    REPLAY = "replay"
    CONFLICT = "conflict"
    IN_PROGRESS = "in_progress"


class DeliveryReplayResultType(StrEnum):
    REPLAY = "replay"
    CONFLICT = "conflict"
    IN_PROGRESS = "in_progress"
    UNKNOWN = "unknown"
    FAILED = "failed"
    NOT_FOUND = "not_found"


class DeliveryCommitResultType(StrEnum):
    COMMITTED = "committed"


class DeliveryClaimResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: DeliveryClaimResultType
    transaction: DeliveryTransactionRecord
    receipt: IdempotencyRecord | None = None


class DeliveryReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: DeliveryReplayResultType
    transaction: DeliveryTransactionRecord | None = None
    receipt: IdempotencyRecord | None = None


class DeliveryCommitResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: DeliveryCommitResultType = DeliveryCommitResultType.COMMITTED
    transaction: DeliveryTransactionRecord
    receipt: IdempotencyRecord
    audit: DeliveryAuditRecord


class DeliveryTransactionPort(Protocol):
    """Coordinate claim, external-action state, and receipt/audit commit only."""

    def claim(
        self,
        *,
        namespace: str,
        action: str,
        key: str,
        request_hash: str,
        owner_id: str,
    ) -> DeliveryClaimResult: ...

    def mark_processing(self, transaction_id: UUID, claim_token: str) -> None: ...

    def mark_unknown(self, transaction_id: UUID, claim_token: str) -> None: ...

    def mark_failed(self, transaction_id: UUID, claim_token: str) -> None: ...

    def commit(
        self,
        transaction_id: UUID,
        claim_token: str,
        receipt: IdempotencyRecord,
        audit: DeliveryAuditRecord,
    ) -> DeliveryCommitResult: ...

    def replay(
        self,
        *,
        namespace: str,
        action: str,
        key: str,
        request_hash: str,
    ) -> DeliveryReplayResult: ...

    def get_state(self, transaction_id: UUID) -> DeliveryTransactionRecord: ...
