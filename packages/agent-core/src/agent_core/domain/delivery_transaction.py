"""Provider-neutral lifecycle for one cloud delivery transaction."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DeliveryTransactionState(StrEnum):
    """Durable states; UNKNOWN is never an automatic retry signal."""

    CLAIMED = "claimed"
    PROCESSING = "processing"
    COMMITTED = "committed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DeliveryTransactionStateError(ValueError):
    """Raised when a requested state transition is not allowed."""


class DeliveryTransactionOwnershipError(ValueError):
    """Raised when a stale or foreign claim token attempts a write."""


class DeliveryTransactionConflictError(ValueError):
    """Raised when one delivery identity is reused for a different request."""


class DeliveryTransactionInvariantError(ValueError):
    """Raised when receipt/audit data cannot satisfy the transaction identity."""


class DeliveryTransactionNotFoundError(LookupError):
    """Raised when a transaction id is not present in the authority store."""


_ALLOWED_TRANSITIONS: dict[DeliveryTransactionState, frozenset[DeliveryTransactionState]] = {
    DeliveryTransactionState.CLAIMED: frozenset({DeliveryTransactionState.PROCESSING}),
    DeliveryTransactionState.PROCESSING: frozenset(
        {
            DeliveryTransactionState.COMMITTED,
            DeliveryTransactionState.FAILED,
            DeliveryTransactionState.UNKNOWN,
        }
    ),
    DeliveryTransactionState.COMMITTED: frozenset(),
    DeliveryTransactionState.FAILED: frozenset(),
    DeliveryTransactionState.UNKNOWN: frozenset(),
}


def validate_delivery_transaction_transition(
    current: DeliveryTransactionState,
    target: DeliveryTransactionState,
) -> None:
    """Validate lifecycle transitions without choosing a recovery policy."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise DeliveryTransactionStateError(
            f"invalid delivery transaction transition: {current} -> {target}"
        )


class DeliveryTransactionRecord(BaseModel):
    """Metadata-only transaction state; it never contains an external payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transaction_id: UUID
    deployment_namespace: str = Field(max_length=255)
    action: str = Field(max_length=255)
    idempotency_key: str = Field(max_length=255)
    request_hash: str = Field(max_length=255)
    state: DeliveryTransactionState
    owner_id: str = Field(max_length=255)
    claim_token: str = Field(max_length=255)
    attempt: int = Field(ge=1)
    receipt_id: str | None = Field(default=None, max_length=255)
    created_at: datetime
    updated_at: datetime
    committed_at: datetime | None = None

    @field_validator(
        "deployment_namespace",
        "action",
        "idempotency_key",
        "request_hash",
        "owner_id",
        "claim_token",
        "receipt_id",
    )
    @classmethod
    def normalize_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("delivery transaction text must not be blank")
        return normalized

    @field_validator("created_at", "updated_at", "committed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("delivery transaction timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.state is DeliveryTransactionState.COMMITTED:
            if self.receipt_id is None or self.committed_at is None:
                raise ValueError("committed transaction requires receipt_id and committed_at")
        elif self.committed_at is not None:
            raise ValueError("only committed transaction may carry committed_at")
        return self
