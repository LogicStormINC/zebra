from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryStatus
from agent_core.domain.memory_delivery import MemoryDeliveryCertainty

MemoryGatewayMutationCertainty = MemoryDeliveryCertainty


class MemoryGatewayStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class ConfirmedMemoryPublication(BaseModel):
    """A governed Zebra memory that may be copied to a derived index."""

    model_config = ConfigDict(frozen=True)

    memory_id: MemoryId
    memory_status: Literal[MemoryStatus.CONFIRMED] = MemoryStatus.CONFIRMED
    namespace: str = Field(max_length=256)
    text: str = Field(max_length=32_768)
    idempotency_key: str = Field(max_length=256)

    @field_validator("namespace", "text", "idempotency_key")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class MemoryGatewaySearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    namespace: str = Field(max_length=256)
    query: str = Field(max_length=4_096)
    limit: int = Field(default=10, ge=1, le=100)

    @field_validator("namespace", "query")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class MemoryGatewayDeleteRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_id: MemoryId
    namespace: str = Field(max_length=256)
    idempotency_key: str = Field(max_length=256)

    @field_validator("namespace", "idempotency_key")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class MemoryGatewayHit(BaseModel):
    """A provider hit that must be revalidated through MemoryStorePort."""

    model_config = ConfigDict(frozen=True)

    memory_id: MemoryId
    provider_ref: str = Field(max_length=512)
    provider_score: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("provider_ref")
    @classmethod
    def normalize_provider_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider_ref must not be blank")
        return normalized


class MemoryGatewayMutationResult(BaseModel):
    """Typed provider outcome; ``detail`` is diagnostic and never a control signal."""

    model_config = ConfigDict(frozen=True)

    status: MemoryGatewayStatus
    provider_ref: str | None = Field(default=None, max_length=512)
    certainty: MemoryDeliveryCertainty | None = None
    detail: str | None = Field(default=None, max_length=1_024)

    @model_validator(mode="after")
    def validate_result(self) -> "MemoryGatewayMutationResult":
        object.__setattr__(self, "provider_ref", _optional_text(self.provider_ref))
        object.__setattr__(self, "detail", _optional_text(self.detail))
        certainty = self.certainty or _default_mutation_certainty(self.status)
        object.__setattr__(self, "certainty", certainty)
        if certainty is MemoryDeliveryCertainty.APPLIED and self.provider_ref is None:
            raise ValueError("successful mutation requires provider_ref")
        if certainty is not MemoryDeliveryCertainty.APPLIED and self.provider_ref is not None:
            raise ValueError("non-successful mutation cannot expose provider_ref")
        if (
            self.status is MemoryGatewayStatus.SUCCEEDED
            and certainty is not MemoryDeliveryCertainty.APPLIED
        ):
            raise ValueError("successful mutation requires applied certainty")
        if (
            self.status is not MemoryGatewayStatus.SUCCEEDED
            and certainty is MemoryDeliveryCertainty.APPLIED
        ):
            raise ValueError("non-successful mutation cannot be applied")
        if (
            self.status
            in {
                MemoryGatewayStatus.DISABLED,
                MemoryGatewayStatus.NOT_FOUND,
            }
            and certainty is not MemoryDeliveryCertainty.DEFINITE_NO_EFFECT
        ):
            raise ValueError(f"{self.status} requires definite_no_effect certainty")
        return self


class MemoryGatewaySearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: MemoryGatewayStatus
    hits: tuple[MemoryGatewayHit, ...] = ()
    detail: str | None = Field(default=None, max_length=1_024)

    @model_validator(mode="after")
    def validate_result(self) -> "MemoryGatewaySearchResult":
        object.__setattr__(self, "detail", _optional_text(self.detail))
        if (
            self.status
            not in {
                MemoryGatewayStatus.SUCCEEDED,
                MemoryGatewayStatus.PARTIAL,
            }
            and self.hits
        ):
            raise ValueError("unavailable search cannot expose hits")
        return self


class AgentMemoryGatewayPort(Protocol):
    def publish(
        self,
        publication: ConfirmedMemoryPublication,
    ) -> MemoryGatewayMutationResult: ...

    def search(self, request: MemoryGatewaySearchRequest) -> MemoryGatewaySearchResult: ...

    def delete(self, request: MemoryGatewayDeleteRequest) -> MemoryGatewayMutationResult: ...


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _default_mutation_certainty(status: MemoryGatewayStatus) -> MemoryDeliveryCertainty:
    """Keep existing adapters source-compatible until they opt into certainty."""

    if status is MemoryGatewayStatus.SUCCEEDED:
        return MemoryDeliveryCertainty.APPLIED
    if status is MemoryGatewayStatus.DEGRADED:
        return MemoryDeliveryCertainty.UNKNOWN
    return MemoryDeliveryCertainty.DEFINITE_NO_EFFECT
