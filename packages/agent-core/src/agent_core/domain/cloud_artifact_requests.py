from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from agent_core.domain.artifact_objects import (
    ArtifactObjectCleanupEvidence,
    ArtifactObjectDeleteResult,
    ArtifactObjectReceipt,
)
from agent_core.domain.identifiers import ArtifactId, EventId, SessionId


def _require_text(value: str, *, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and trimmed")
    return value


def _require_timestamp(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class ArtifactManagementContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: UUID
    operator_id: str = Field(max_length=255)
    reason: str = Field(max_length=1024)

    @field_validator("operator_id", "reason")
    @classmethod
    def require_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_text(value, field_name=info.field_name or "field")


class ArtifactReserveRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: ArtifactId
    session_id: SessionId
    intended_event_sequence: int = Field(ge=0)
    kind: str = Field(max_length=255)
    mime_type: str = Field(max_length=255)
    sha256: str
    size_bytes: int = Field(ge=0)
    idempotency_key: str = Field(max_length=255)
    file_name: str | None = Field(default=None, max_length=1024)
    retained_until: datetime | None = None
    created_at: datetime

    @field_validator("kind", "mime_type", "idempotency_key")
    @classmethod
    def require_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_text(value, field_name=info.field_name or "field")

    @field_validator("file_name")
    @classmethod
    def normalize_file_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_text(value, field_name="file_name")

    @field_validator("sha256")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        return value

    @field_validator("created_at")
    @classmethod
    def require_created_at(cls, value: datetime) -> datetime:
        return _require_timestamp(value, field_name="created_at")

    @field_validator("retained_until")
    @classmethod
    def require_retained_until(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_timestamp(value, field_name="retained_until")

    @model_validator(mode="after")
    def require_retention_after_creation(self) -> Self:
        if self.retained_until is not None and self.retained_until < self.created_at:
            raise ValueError("retained_until must not precede created_at")
        return self


class ArtifactEventBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    event_id: EventId
    sequence: int = Field(ge=0)
    artifact_uri: str = Field(max_length=2048)

    @field_validator("artifact_uri")
    @classmethod
    def require_artifact_uri(cls, value: str) -> str:
        return _require_text(value, field_name="artifact_uri")


class _ArtifactMutationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: ArtifactId
    session_id: SessionId
    expected_lifecycle_revision: int = Field(ge=0)
    idempotency_key: str = Field(max_length=255)

    @field_validator("idempotency_key")
    @classmethod
    def require_idempotency_key(cls, value: str) -> str:
        return _require_text(value, field_name="idempotency_key")


class ArtifactRecordObjectRequest(_ArtifactMutationRequest):
    object_receipt: ArtifactObjectReceipt

    @model_validator(mode="after")
    def require_object_artifact(self) -> Self:
        if self.object_receipt.expectation.artifact_id != self.artifact_id:
            raise ValueError("object receipt artifact_id does not match request")
        return self


class ArtifactFinalizeRequest(_ArtifactMutationRequest):
    event_binding: ArtifactEventBinding
    object_receipt: ArtifactObjectReceipt
    finalized_at: datetime

    @field_validator("finalized_at")
    @classmethod
    def require_finalized_at(cls, value: datetime) -> datetime:
        return _require_timestamp(value, field_name="finalized_at")

    @model_validator(mode="after")
    def require_exact_binding(self) -> Self:
        if self.object_receipt.expectation.artifact_id != self.artifact_id:
            raise ValueError("object receipt artifact_id does not match request")
        if self.event_binding.session_id != self.session_id:
            raise ValueError("Event session_id does not match request")
        if self.event_binding.artifact_uri != f"artifact://{self.artifact_id}":
            raise ValueError("Event artifact_uri does not match request")
        return self


class ArtifactCompensateRequest(_ArtifactMutationRequest):
    object_cleanup: ArtifactObjectCleanupEvidence
    compensated_at: datetime

    @field_validator("compensated_at")
    @classmethod
    def require_compensated_at(cls, value: datetime) -> datetime:
        return _require_timestamp(value, field_name="compensated_at")

    @model_validator(mode="after")
    def require_object_artifact(self) -> Self:
        deletion = self.object_cleanup.deletion
        verification = self.object_cleanup.verification
        if deletion is not None and deletion.request.expectation.artifact_id != self.artifact_id:
            raise ValueError("object delete artifact_id does not match request")
        if verification is not None and verification.expectation.artifact_id != self.artifact_id:
            raise ValueError("object verification artifact_id does not match request")
        return self


class ArtifactBeginPruneRequest(_ArtifactMutationRequest):
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def require_requested_at(cls, value: datetime) -> datetime:
        return _require_timestamp(value, field_name="requested_at")


class ArtifactCompletePruneRequest(_ArtifactMutationRequest):
    object_delete: ArtifactObjectDeleteResult
    pruned_at: datetime

    @field_validator("pruned_at")
    @classmethod
    def require_pruned_at(cls, value: datetime) -> datetime:
        return _require_timestamp(value, field_name="pruned_at")

    @model_validator(mode="after")
    def require_object_artifact(self) -> Self:
        if self.object_delete.request.expectation.artifact_id != self.artifact_id:
            raise ValueError("object delete artifact_id does not match request")
        return self


class ArtifactMetadataQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: str = Field(max_length=255)
    artifact_id: ArtifactId
    session_id: SessionId

    @field_validator("deployment_namespace")
    @classmethod
    def require_namespace(cls, value: str) -> str:
        return _require_text(value, field_name="deployment_namespace")


class ArtifactReconcileQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    older_than: datetime
    limit: int = Field(default=100, ge=1, le=1000)

    @field_validator("older_than")
    @classmethod
    def require_older_than(cls, value: datetime) -> datetime:
        return _require_timestamp(value, field_name="older_than")
