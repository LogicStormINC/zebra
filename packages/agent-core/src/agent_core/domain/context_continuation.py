from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.identifiers import EventId, SessionId
from agent_core.domain.leases import LeaseFence


class ProviderContinuationMode(StrEnum):
    NONE = "none"
    OPAQUE_REFERENCE = "opaque_reference"


class ProviderContinuationCapability(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: ProviderContinuationMode = ProviderContinuationMode.NONE
    capability_version: str = "1"
    same_provider_only: bool = True
    same_model_only: bool = True
    recoverable_across_workers: bool = False
    maximum_ttl_seconds: int | None = Field(default=None, gt=0)

    @field_validator("capability_version")
    @classmethod
    def ensure_version(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider continuation capability version must not be blank")
        return stripped


class ProviderContinuationRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_id: str
    provider: str
    model_name: str
    capability_version: str = "1"
    source_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    @field_validator("reference_id", "provider", "model_name", "capability_version", "source_hash")
    @classmethod
    def ensure_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider continuation fields must not be blank")
        return stripped

    @model_validator(mode="after")
    def ensure_timestamps(self) -> "ProviderContinuationRef":
        if self.created_at.tzinfo is None:
            raise ValueError("provider continuation created_at must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                raise ValueError("provider continuation expiry must be timezone-aware")
            if self.expires_at <= self.created_at:
                raise ValueError("provider continuation expiry must follow creation")
        return self


class ProviderContinuationArtifact(BaseModel):
    """Tenant-scoped durable opaque provider state."""

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    tenant_id: str
    session_id: str
    reference: ProviderContinuationRef
    payload_sha256: str
    size_bytes: int = Field(ge=0)
    deleted_at: datetime | None = None

    @field_validator("artifact_id", "tenant_id", "session_id", "payload_sha256")
    @classmethod
    def ensure_artifact_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provider continuation artifact fields must not be blank")
        return stripped

    @field_validator("deleted_at")
    @classmethod
    def ensure_deleted_at_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("provider continuation deleted_at must be timezone-aware")
        return value

    def is_compatible(
        self,
        *,
        provider: str,
        model_name: str,
        capability_version: str,
        as_of: datetime,
    ) -> bool:
        if as_of.tzinfo is None:
            raise ValueError("compatibility timestamp must be timezone-aware")
        return (
            self.deleted_at is None
            and self.reference.provider == provider
            and self.reference.model_name == model_name
            and self.reference.capability_version == capability_version
            and (self.reference.expires_at is None or self.reference.expires_at > as_of)
        )


class CloudProviderContinuationArtifact(BaseModel):
    """Authority-scoped cloud continuation metadata and audit evidence.

    This model is deliberately separate from ``ProviderContinuationArtifact``:
    the latter is the local SQLite compatibility surface and keeps its historic
    ``tenant_id`` contract. Cloud storage records the opaque external authority
    and the internal deployment partition explicitly instead of deriving either
    from provider state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    continuation_id: str
    scope: OpaqueAuthorityScope
    deployment_namespace: str
    session_id: SessionId
    reference: ProviderContinuationRef
    payload_sha256: str
    size_bytes: int = Field(ge=0)
    lifecycle_revision: int = Field(ge=0)
    selection_event_id: EventId
    selection_event_sequence: int = Field(ge=0)
    idempotency_key: str
    accepted_lease: LeaseFence
    deleted_at: datetime | None = None

    @field_validator(
        "continuation_id",
        "deployment_namespace",
        "payload_sha256",
        "idempotency_key",
    )
    @classmethod
    def ensure_cloud_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("cloud provider continuation fields must not be blank")
        return normalized

    @field_validator("payload_sha256")
    @classmethod
    def ensure_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("cloud provider continuation payload_sha256 must be lowercase SHA-256")
        return normalized

    @field_validator("deleted_at")
    @classmethod
    def ensure_deleted_at_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("cloud provider continuation deleted_at must be timezone-aware")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def ensure_scope_and_identity(self) -> "CloudProviderContinuationArtifact":
        if self.deployment_namespace != self.deployment_namespace.strip():
            raise ValueError("deployment namespace must be trimmed")
        if self.reference.expires_at is None:
            raise ValueError("cloud provider continuation requires an expiry")
        if self.deleted_at is not None and self.deleted_at < self.reference.created_at:
            raise ValueError("cloud provider continuation deletion precedes creation")
        return self

    @property
    def artifact_id(self) -> str:
        """Compatibility name used by the local continuation Event contract."""

        return self.continuation_id

    def is_compatible(
        self,
        *,
        scope: OpaqueAuthorityScope,
        session_id: SessionId,
        provider: str,
        model_name: str,
        capability_version: str,
        as_of: datetime,
    ) -> bool:
        if as_of.tzinfo is None:
            raise ValueError("compatibility timestamp must be timezone-aware")
        return (
            self.scope.scope_key == scope.scope_key
            and scope.allows_session(session_id)
            and self.session_id == session_id
            and self.deleted_at is None
            and self.reference.provider == provider
            and self.reference.model_name == model_name
            and self.reference.capability_version == capability_version
            and self.reference.expires_at is not None
            and self.reference.expires_at > as_of
        )
