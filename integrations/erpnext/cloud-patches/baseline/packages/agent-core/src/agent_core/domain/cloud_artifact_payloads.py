from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.cloud_artifact_requests import (
    ArtifactEventBinding,
    ArtifactReserveRequest,
)
from agent_core.domain.identifiers import ArtifactId, SessionId


class CloudArtifactPayloadLifecycleStatus(StrEnum):
    STAGED = "staged"
    FINALIZED = "finalized"
    COMPENSATED = "compensated"
    PRUNING = "pruning"
    PRUNED = "pruned"


class CloudArtifactPayloadConflictError(ValueError):
    """Raised when an idempotency identity is reused with different meaning."""


class CloudArtifactPayloadStateError(ValueError):
    """Raised when a lifecycle transition is not allowed."""


class CloudArtifactPayloadNotFoundError(LookupError):
    """Raised when authoritative Artifact metadata does not exist."""


def _require_text(value: str, *, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and trimmed")
    return value


def _require_timestamp(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class CloudArtifactPayloadRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: str = Field(max_length=255)
    reservation: ArtifactReserveRequest
    lifecycle_status: CloudArtifactPayloadLifecycleStatus
    lifecycle_revision: int = Field(ge=0)
    event_binding: ArtifactEventBinding | None = None
    object_receipt: ArtifactObjectReceipt | None = None
    finalized_at: datetime | None = None
    compensated_at: datetime | None = None
    pruning_at: datetime | None = None
    pruned_at: datetime | None = None

    @field_validator("deployment_namespace")
    @classmethod
    def require_namespace(cls, value: str) -> str:
        return _require_text(value, field_name="deployment_namespace")

    @field_validator(
        "finalized_at",
        "compensated_at",
        "pruning_at",
        "pruned_at",
    )
    @classmethod
    def require_optional_timestamp(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        if value is None:
            return None
        return _require_timestamp(value, field_name=info.field_name or "timestamp")

    @model_validator(mode="after")
    def require_lifecycle_shape(self) -> Self:
        self._require_object_receipt_binding()
        self._require_event_binding()
        finalized_proof = all(
            value is not None
            for value in (self.event_binding, self.object_receipt, self.finalized_at)
        )
        if self.lifecycle_status is CloudArtifactPayloadLifecycleStatus.STAGED:
            if any(
                value is not None
                for value in (
                    self.event_binding,
                    self.finalized_at,
                    self.compensated_at,
                    self.pruning_at,
                    self.pruned_at,
                )
            ):
                raise ValueError("staged metadata cannot carry terminal lifecycle evidence")
        elif self.lifecycle_status is CloudArtifactPayloadLifecycleStatus.COMPENSATED:
            if (
                self.compensated_at is None
                or self.event_binding is not None
                or self.finalized_at is not None
                or self.pruning_at is not None
                or self.pruned_at is not None
            ):
                raise ValueError("compensated metadata requires only compensation evidence")
        else:
            if not finalized_proof:
                raise ValueError("readable and pruning metadata requires finalized proof")
            if self.compensated_at is not None:
                raise ValueError("finalized and pruning metadata cannot be compensated")
            if self.lifecycle_status is CloudArtifactPayloadLifecycleStatus.FINALIZED:
                if self.pruning_at is not None or self.pruned_at is not None:
                    raise ValueError("finalized metadata cannot carry prune evidence")
            elif self.lifecycle_status is CloudArtifactPayloadLifecycleStatus.PRUNING:
                if self.pruning_at is None or self.pruned_at is not None:
                    raise ValueError("pruning metadata requires only prune-start evidence")
            elif self.pruning_at is None or self.pruned_at is None:
                raise ValueError("pruned metadata requires complete prune evidence")
        return self

    def _require_object_receipt_binding(self) -> None:
        if self.object_receipt is None:
            return
        expectation = self.object_receipt.expectation
        if (
            expectation.deployment_namespace != self.deployment_namespace
            or expectation.artifact_id != self.artifact_id
            or expectation.sha256 != self.reservation.sha256
            or expectation.size_bytes != self.reservation.size_bytes
        ):
            raise ValueError("object receipt does not match reserved payload")

    def _require_event_binding(self) -> None:
        if self.event_binding is None:
            return
        if (
            self.event_binding.session_id != self.session_id
            or self.event_binding.sequence != self.reservation.intended_event_sequence
            or self.event_binding.artifact_uri != self.uri
        ):
            raise ValueError("Event binding does not match reserved payload")

    @property
    def artifact_id(self) -> ArtifactId:
        return self.reservation.artifact_id

    @property
    def session_id(self) -> SessionId:
        return self.reservation.session_id

    @property
    def uri(self) -> str:
        return f"artifact://{self.artifact_id}"
