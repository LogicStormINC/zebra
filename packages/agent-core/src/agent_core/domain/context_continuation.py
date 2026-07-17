from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ProviderContinuationMode(StrEnum):
    NONE = "none"
    OPAQUE_REFERENCE = "opaque_reference"


class ProviderContinuationCapability(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: ProviderContinuationMode = ProviderContinuationMode.NONE
    same_provider_only: bool = True
    recoverable_across_workers: bool = False


class ProviderContinuationRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_id: str
    provider: str
    model_name: str
    source_hash: str
    expires_at: datetime | None = None

    @field_validator("reference_id", "provider", "model_name", "source_hash")
    @classmethod
    def ensure_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider continuation fields must not be blank")
        return stripped

    @model_validator(mode="after")
    def ensure_expiry_is_aware(self) -> "ProviderContinuationRef":
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("provider continuation expiry must be timezone-aware")
        return self
