"""Canonical resource and verification evidence for post-mutation checks."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    STALE = "stale"
    FAILED = "failed"


class VerificationResourceRef(BaseModel):
    """Authority-qualified resource identity; never inferred from field names."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authority_issuer: str = Field(min_length=1, max_length=256)
    namespace_id: str = Field(min_length=1, max_length=512)
    host_app_id: str = Field(min_length=1, max_length=128)
    resource_type: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=512)

    @property
    def key(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "resource:" + hashlib.sha256(encoded).hexdigest()


class VerificationEvidence(BaseModel):
    """Bounded proof connecting one mutation, read and postcondition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_ref: VerificationResourceRef
    mutation_effect_id: str | None = Field(default=None, max_length=256)
    host_receipt_ref: str | None = Field(default=None, max_length=512)
    commit_version: str | None = Field(default=None, max_length=256)
    read_version: str | None = Field(default=None, max_length=256)
    observed_epoch: int = Field(ge=0)
    postcondition: str | None = Field(default=None, max_length=512)
    verification_status: VerificationStatus
