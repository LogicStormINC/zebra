from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import ArtifactId


class ArtifactObjectVerificationStatus(StrEnum):
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    MISMATCH = "mismatch"


class ArtifactObjectDeleteStatus(StrEnum):
    DELETED = "deleted"
    ALREADY_ABSENT = "already_absent"


class ArtifactObjectConflictError(ValueError):
    """Raised when an immutable object identity is reused with different content."""


class ArtifactObjectNotFoundError(FileNotFoundError):
    """Raised when verified object bytes do not exist."""


class ArtifactObjectIntegrityError(RuntimeError):
    """Raised when object bytes do not match the authoritative expectation."""


class ArtifactObjectUnavailableError(RuntimeError):
    """Raised when object state cannot be determined safely."""


class ArtifactObjectExpectation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: str = Field(max_length=255)
    artifact_id: ArtifactId
    sha256: str
    size_bytes: int = Field(ge=0)

    @field_validator("deployment_namespace")
    @classmethod
    def require_namespace(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("deployment_namespace must be non-blank and trimmed")
        return value

    @field_validator("sha256")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        return value


class ArtifactObjectPutRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expectation: ArtifactObjectExpectation
    payload: bytes

    @model_validator(mode="after")
    def require_expected_content(self) -> Self:
        if len(self.payload) != self.expectation.size_bytes:
            raise ValueError("payload size does not match object expectation")
        if sha256(self.payload).hexdigest() != self.expectation.sha256:
            raise ValueError("payload digest does not match object expectation")
        return self


class ArtifactObjectReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expectation: ArtifactObjectExpectation
    object_version: str = Field(max_length=1024)
    verified_at: datetime

    @field_validator("object_version")
    @classmethod
    def require_object_version(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("object_version must be non-blank and trimmed")
        return value

    @field_validator("verified_at")
    @classmethod
    def require_verified_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("verified_at must be timezone-aware")
        return value


class ArtifactObjectVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expectation: ArtifactObjectExpectation
    status: ArtifactObjectVerificationStatus
    receipt: ArtifactObjectReceipt | None = None

    @model_validator(mode="after")
    def require_status_shape(self) -> Self:
        if (self.status is ArtifactObjectVerificationStatus.VERIFIED) != (
            self.receipt is not None
        ):
            raise ValueError("only verified object inspections carry a receipt")
        if self.receipt is not None and self.receipt.expectation != self.expectation:
            raise ValueError("object receipt does not match the inspected expectation")
        return self


class ArtifactObjectDeleteRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expectation: ArtifactObjectExpectation
    object_version: str = Field(max_length=1024)

    @field_validator("object_version")
    @classmethod
    def require_object_version(cls, value: str) -> str:
        return ArtifactObjectReceipt.require_object_version(value)


class ArtifactObjectDeleteResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request: ArtifactObjectDeleteRequest
    status: ArtifactObjectDeleteStatus


class ArtifactObjectCleanupEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verification: ArtifactObjectVerification | None = None
    deletion: ArtifactObjectDeleteResult | None = None

    @model_validator(mode="after")
    def require_safe_cleanup(self) -> Self:
        if (self.verification is None) == (self.deletion is None):
            raise ValueError("cleanup evidence requires exactly one outcome")
        if (
            self.verification is not None
            and self.verification.status is not ArtifactObjectVerificationStatus.NOT_FOUND
        ):
            raise ValueError("verification cleanup evidence must prove object absence")
        return self
