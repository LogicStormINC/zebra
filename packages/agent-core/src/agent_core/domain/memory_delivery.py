"""Provider-neutral contracts for derived memory delivery."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import MemoryId


class MemoryDeliveryOperation(StrEnum):
    """The authoritative lifecycle change being delivered to a derived index."""

    PUBLISH = "publish"
    DELETE = "delete"


class MemoryDeliveryState(StrEnum):
    """Durable operation states shared by storage and the delivery worker."""

    PENDING = "pending"
    CLAIMED = "claimed"
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"
    DEAD_LETTER = "dead_letter"


class MemoryDeliveryCertainty(StrEnum):
    """What a provider response proves about a mutation."""

    APPLIED = "applied"
    DEFINITE_NO_EFFECT = "definite_no_effect"
    UNKNOWN = "unknown"


class MemoryDeliveryScopeState(StrEnum):
    """Lifecycle of one provider namespace generation."""

    ACTIVE = "active"
    QUARANTINED = "quarantined"
    REBUILDING = "rebuilding"


class MemoryDeliveryScope(BaseModel):
    """An opaque, generation-scoped namespace for a derived memory index."""

    model_config = ConfigDict(frozen=True)

    deployment_namespace: str = Field(max_length=256)
    scope_digest: str = Field(min_length=64, max_length=64)
    generation: int = Field(ge=1)
    state: MemoryDeliveryScopeState = MemoryDeliveryScopeState.ACTIVE
    revision: int = Field(ge=0)

    @field_validator("deployment_namespace")
    @classmethod
    def normalize_namespace(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("deployment_namespace must not be blank")
        return normalized

    @field_validator("scope_digest")
    @classmethod
    def validate_scope_digest(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("scope_digest must be a lowercase SHA-256 digest")
        return normalized


class MemoryDeliveryOperationRecord(BaseModel):
    """Metadata-only operation identity; the record intentionally has no text field."""

    model_config = ConfigDict(frozen=True)

    memory_id: MemoryId
    operation: MemoryDeliveryOperation
    scope_digest: str = Field(min_length=64, max_length=64)
    generation: int = Field(ge=1)
    memory_revision: int = Field(ge=1)
    content_digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(max_length=256)
    state: MemoryDeliveryState = MemoryDeliveryState.PENDING
    attempt: int = Field(default=0, ge=0)
    certainty: MemoryDeliveryCertainty | None = None

    @field_validator("scope_digest", "content_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("digest must be a lowercase SHA-256 digest")
        return normalized

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_certainty(self) -> Self:
        _validate_state_certainty(self.state, self.certainty)
        return self

    def transition(
        self,
        state: MemoryDeliveryState,
        *,
        certainty: MemoryDeliveryCertainty | None = None,
        attempt: int | None = None,
    ) -> Self:
        """Return a validated state transition; storage supplies the CAS boundary."""

        validate_memory_delivery_transition(self.state, state, certainty=certainty)
        next_attempt = self.attempt if attempt is None else attempt
        if next_attempt < self.attempt:
            raise ValueError("delivery attempt cannot decrease")
        return self.model_copy(
            update={"state": state, "certainty": certainty, "attempt": next_attempt}
        )


class MemoryDeliveryTransition(BaseModel):
    """A provider-neutral CAS request for one operation state change."""

    model_config = ConfigDict(frozen=True)

    idempotency_key: str = Field(max_length=256)
    expected_state: MemoryDeliveryState
    next_state: MemoryDeliveryState
    certainty: MemoryDeliveryCertainty | None = None
    claim_token: str | None = Field(default=None, max_length=256)

    @field_validator("idempotency_key", "claim_token")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("delivery transition text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        validate_memory_delivery_transition(
            self.expected_state,
            self.next_state,
            certainty=self.certainty,
        )
        return self


_ALLOWED_TRANSITIONS: dict[MemoryDeliveryState, frozenset[MemoryDeliveryState]] = {
    MemoryDeliveryState.PENDING: frozenset(
        {MemoryDeliveryState.CLAIMED, MemoryDeliveryState.DEAD_LETTER}
    ),
    MemoryDeliveryState.CLAIMED: frozenset(
        {MemoryDeliveryState.PENDING, MemoryDeliveryState.IN_FLIGHT}
    ),
    MemoryDeliveryState.IN_FLIGHT: frozenset(
        {
            MemoryDeliveryState.PENDING,
            MemoryDeliveryState.COMPLETED,
            MemoryDeliveryState.UNCERTAIN,
        }
    ),
    MemoryDeliveryState.COMPLETED: frozenset(),
    MemoryDeliveryState.UNCERTAIN: frozenset(),
    MemoryDeliveryState.DEAD_LETTER: frozenset(),
}


def validate_memory_delivery_transition(
    current: MemoryDeliveryState,
    target: MemoryDeliveryState,
    *,
    certainty: MemoryDeliveryCertainty | None = None,
) -> None:
    """Validate state and certainty without deciding storage or retry policy."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid memory delivery transition: {current} -> {target}")
    _validate_state_certainty(target, certainty)


def _validate_state_certainty(
    state: MemoryDeliveryState,
    certainty: MemoryDeliveryCertainty | None,
) -> None:
    if state in {MemoryDeliveryState.PENDING, MemoryDeliveryState.CLAIMED}:
        if certainty not in {None, MemoryDeliveryCertainty.DEFINITE_NO_EFFECT}:
            raise ValueError(f"{state} cannot carry {certainty} certainty")
        return
    if state is MemoryDeliveryState.IN_FLIGHT:
        if certainty is not None:
            raise ValueError("in_flight cannot carry provider certainty")
        return
    if state is MemoryDeliveryState.COMPLETED:
        if certainty not in {
            MemoryDeliveryCertainty.APPLIED,
            MemoryDeliveryCertainty.DEFINITE_NO_EFFECT,
        }:
            raise ValueError("completed requires applied or definite_no_effect certainty")
        return
    if state is MemoryDeliveryState.UNCERTAIN:
        if certainty is not MemoryDeliveryCertainty.UNKNOWN:
            raise ValueError("uncertain requires unknown certainty")
        return
    if certainty is not MemoryDeliveryCertainty.DEFINITE_NO_EFFECT:
        raise ValueError("dead_letter requires definite_no_effect certainty")
