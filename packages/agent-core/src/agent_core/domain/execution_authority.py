from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.execution_authority_support import (
    digest,
    normalize_digest,
    reject_secret_material,
)
from agent_core.domain.identifiers import SessionId

_MAX_TEXT_LENGTH = 2_048
_MAX_CAPABILITIES = 256
_MAX_CAPABILITY_LENGTH = 128


class ExecutionAuthorityResolutionError(ValueError):
    """Raised when an Attempt authority cannot be resolved safely."""


class ExecutionAuthorityDecision(StrEnum):
    ALLOWED = "allowed"
    NARROWED = "narrowed"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ExecutionAuthorityLimits(BaseModel):
    """Technical limits that may only stay equal or become narrower."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_concurrent_tasks: int | None = Field(default=None, gt=0)
    max_model_tokens: int | None = Field(default=None, gt=0)
    max_runtime_seconds: int | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, gt=0)

    def narrowed_by(self, *limits: ExecutionAuthorityLimits) -> ExecutionAuthorityLimits:
        values: dict[str, int | None] = {}
        for field_name in type(self).model_fields:
            candidates = [getattr(candidate, field_name) for candidate in (self, *limits)]
            bounded = [value for value in candidates if value is not None]
            values[field_name] = min(bounded) if bounded else None
        return type(self).model_validate(values)

    def is_no_broader_than(self, other: ExecutionAuthorityLimits) -> bool:
        for field_name in type(self).model_fields:
            current = getattr(self, field_name)
            previous = getattr(other, field_name)
            if current is None:
                if previous is not None:
                    return False
            elif previous is not None and current > previous:
                return False
        return True


class ExternalAuthorityGrant(BaseModel):
    """Verified, secret-free evidence supplied by an external authority adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: OpaqueAuthorityScope
    subject: str = Field(min_length=1, max_length=_MAX_TEXT_LENGTH)
    audience: str = Field(min_length=1, max_length=128)
    granted_authorities: tuple[str, ...] = Field(
        min_length=1,
        max_length=_MAX_CAPABILITIES,
    )
    limits: ExecutionAuthorityLimits
    issued_at: datetime
    expires_at: datetime
    source_authority_digest: str = Field(min_length=64, max_length=71)
    revoked: bool = False

    @field_validator("subject", "audience")
    @classmethod
    def normalize_safe_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("authority text must not be blank")
        reject_secret_material(normalized)
        return normalized

    @field_validator("granted_authorities", mode="before")
    @classmethod
    def normalize_authorities(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str) or not isinstance(value, Sequence):
            raise ValueError("granted_authorities must be a sequence")
        normalized = tuple(sorted({str(item).strip() for item in value}))
        if not normalized or any(
            not item or len(item) > _MAX_CAPABILITY_LENGTH or "bearer " in item.casefold()
            for item in normalized
        ):
            raise ValueError("granted authority names must be bounded and non-blank")
        return normalized

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("authority timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("source_authority_digest")
    @classmethod
    def normalize_digest(cls, value: str) -> str:
        return normalize_digest(value, field_name="source_authority_digest")

    @model_validator(mode="after")
    def validate_window(self) -> ExternalAuthorityGrant:
        if self.expires_at <= self.issued_at:
            raise ValueError("authority expires_at must be after issued_at")
        return self


class ExecutionAuthorityResolutionRequest(BaseModel):
    """Inputs available to a resolver without exposing raw credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    attempt_number: int = Field(ge=1)
    scope: OpaqueAuthorityScope
    authority_grant: ExternalAuthorityGrant | None = None
    agent_definition_snapshot_digest: str | None = None
    capability_ceiling: tuple[str, ...] | None = None
    validated_at: datetime

    @field_validator("validated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("validated_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("agent_definition_snapshot_digest")
    @classmethod
    def normalize_definition_digest(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_digest(value, field_name="agent_definition_snapshot_digest")

    @field_validator("capability_ceiling", mode="before")
    @classmethod
    def normalize_capability_ceiling(cls, value: object) -> tuple[str, ...] | None:
        if value is None:
            return None
        if isinstance(value, str) or not isinstance(value, Sequence):
            raise ValueError("capability_ceiling must be a sequence")
        normalized = tuple(sorted({str(item).strip() for item in value}))
        if any(not item for item in normalized):
            raise ValueError("capability_ceiling cannot contain blank values")
        return normalized

    @model_validator(mode="after")
    def validate_scope_and_grant(self) -> ExecutionAuthorityResolutionRequest:
        if not self.scope.allows_session(self.session_id):
            raise ValueError("authority scope does not allow this session")
        if self.authority_grant is not None and self.authority_grant.scope != self.scope:
            raise ValueError("authority grant scope does not match resolution scope")
        return self


class ExecutionAuthoritySnapshot(BaseModel):
    """Immutable, secret-free authority captured for one Harness Attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="execution-authority/1", max_length=64)
    attempt_number: int = Field(ge=1)
    authority_issuer: str = Field(min_length=1, max_length=_MAX_TEXT_LENGTH)
    subject: str = Field(min_length=1, max_length=_MAX_TEXT_LENGTH)
    audience: str = Field(min_length=1, max_length=128)
    namespace_id: str = Field(min_length=1, max_length=255)
    granted_authorities: tuple[str, ...] = Field(
        min_length=1,
        max_length=_MAX_CAPABILITIES,
    )
    external_limits: ExecutionAuthorityLimits
    effective_limits: ExecutionAuthorityLimits
    issued_at: datetime
    expires_at: datetime
    validated_at: datetime
    source_authority_digest: str = Field(min_length=64, max_length=71)
    policy_ref: str = Field(min_length=1, max_length=_MAX_TEXT_LENGTH)
    policy_version: str = Field(min_length=1, max_length=128)
    policy_effective_digest: str = Field(min_length=64, max_length=71)
    agent_definition_snapshot_digest: str | None = None
    resolution: ExecutionAuthorityDecision = ExecutionAuthorityDecision.ALLOWED
    snapshot_digest: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("authority_issuer", "subject", "audience", "namespace_id")
    @classmethod
    def normalize_identity_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("authority identity fields must not be blank")
        reject_secret_material(normalized)
        return normalized

    @field_validator("policy_ref")
    @classmethod
    def normalize_policy_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not re.search(r"@[0-9]+$", normalized):
            raise ValueError("policy references must be stable and pinned")
        reject_secret_material(normalized)
        return normalized

    @field_validator("policy_version")
    @classmethod
    def normalize_policy_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("policy version must not be blank")
        reject_secret_material(normalized)
        return normalized

    @field_validator("granted_authorities", mode="before")
    @classmethod
    def normalize_authorities(cls, value: object) -> tuple[str, ...]:
        return ExternalAuthorityGrant.normalize_authorities(value)

    @field_validator("issued_at", "expires_at", "validated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("authority timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator(
        "source_authority_digest",
        "policy_effective_digest",
        "agent_definition_snapshot_digest",
    )
    @classmethod
    def normalize_digests(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return normalize_digest(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_and_bind_digest(self) -> ExecutionAuthoritySnapshot:
        if self.expires_at <= self.issued_at:
            raise ValueError("authority expires_at must be after issued_at")
        if self.validated_at < self.issued_at:
            raise ValueError("validated_at cannot precede issued_at")
        if self.effective_limits.is_no_broader_than(self.external_limits) is False:
            raise ValueError("effective limits cannot expand external limits")
        snapshot_digest = digest(self._canonical_payload())
        if self.snapshot_digest is None:
            object.__setattr__(self, "snapshot_digest", snapshot_digest)
        elif self.snapshot_digest != snapshot_digest:
            raise ValueError("snapshot_digest does not match canonical authority payload")
        return self

    @property
    def scope(self) -> OpaqueAuthorityScope:
        return OpaqueAuthorityScope(
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
        )

    @classmethod
    def from_request(
        cls,
        request: ExecutionAuthorityResolutionRequest,
        *,
        policy_ref: str,
        policy_version: str,
        policy_effective_digest: str,
        runtime_authorities: tuple[str, ...] | None = None,
        policy_authorities: tuple[str, ...] | None = None,
        external_limits: ExecutionAuthorityLimits | None = None,
        runtime_limits: ExecutionAuthorityLimits | None = None,
        policy_limits: ExecutionAuthorityLimits | None = None,
    ) -> ExecutionAuthoritySnapshot:
        grant = request.authority_grant
        if grant is None:
            raise ExecutionAuthorityResolutionError(
                "external authority grant is required unless a trusted resolver supplies one"
            )
        if grant.revoked:
            raise ExecutionAuthorityResolutionError("external authority grant is revoked")
        if request.validated_at < grant.issued_at or request.validated_at >= grant.expires_at:
            raise ExecutionAuthorityResolutionError("external authority grant is expired")
        allowed = set(grant.granted_authorities)
        for ceiling in (request.capability_ceiling, policy_authorities, runtime_authorities):
            if ceiling is not None:
                allowed.intersection_update(ceiling)
        if not allowed:
            raise ExecutionAuthorityResolutionError("authority narrowing leaves no capabilities")
        effective_limits = grant.limits.narrowed_by(
            *(limit for limit in (external_limits, policy_limits, runtime_limits) if limit)
        )
        resolution = (
            ExecutionAuthorityDecision.ALLOWED
            if tuple(sorted(allowed)) == grant.granted_authorities
            and effective_limits == grant.limits
            else ExecutionAuthorityDecision.NARROWED
        )
        return cls(
            attempt_number=request.attempt_number,
            authority_issuer=grant.scope.authority_issuer,
            subject=grant.subject,
            audience=grant.audience,
            namespace_id=grant.scope.namespace_id,
            granted_authorities=tuple(sorted(allowed)),
            external_limits=grant.limits,
            effective_limits=effective_limits,
            issued_at=grant.issued_at,
            expires_at=grant.expires_at,
            validated_at=request.validated_at,
            source_authority_digest=grant.source_authority_digest,
            policy_ref=policy_ref,
            policy_version=policy_version,
            policy_effective_digest=policy_effective_digest,
            agent_definition_snapshot_digest=request.agent_definition_snapshot_digest,
            resolution=resolution,
        )

    def ensure_not_expanded(self, replacement: ExecutionAuthoritySnapshot) -> None:
        if replacement.attempt_number != self.attempt_number:
            raise ExecutionAuthorityResolutionError(
                "same-Attempt authority revalidation changed attempt number"
            )
        if replacement.scope != self.scope:
            raise ExecutionAuthorityResolutionError(
                "same-Attempt authority revalidation changed namespace"
            )
        if replacement.agent_definition_snapshot_digest != self.agent_definition_snapshot_digest:
            raise ExecutionAuthorityResolutionError(
                "same-Attempt authority revalidation changed Definition snapshot"
            )
        if not set(replacement.granted_authorities).issubset(self.granted_authorities):
            raise ExecutionAuthorityResolutionError(
                "same-Attempt authority revalidation expanded capabilities"
            )
        if not replacement.effective_limits.is_no_broader_than(self.effective_limits):
            raise ExecutionAuthorityResolutionError(
                "same-Attempt authority revalidation expanded limits"
            )
        if replacement.expires_at > self.expires_at:
            raise ExecutionAuthorityResolutionError(
                "same-Attempt authority revalidation extended expiry"
            )

    def to_event_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def _canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude={"snapshot_digest"})
        return payload


class ExecutionAuthorityRevalidationRequest(BaseModel):
    """Inputs for checking an already durable Attempt snapshot again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    attempt_number: int = Field(ge=1)
    scope: OpaqueAuthorityScope
    prior_snapshot: ExecutionAuthoritySnapshot
    authority_grant: ExternalAuthorityGrant | None = None
    capability_ceiling: tuple[str, ...] | None = None
    validated_at: datetime

    @field_validator("validated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("validated_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("capability_ceiling", mode="before")
    @classmethod
    def normalize_capability_ceiling(cls, value: object) -> tuple[str, ...] | None:
        if value is None:
            return None
        if isinstance(value, str) or not isinstance(value, Sequence):
            raise ValueError("capability_ceiling must be a sequence")
        normalized = tuple(sorted({str(item).strip() for item in value}))
        if any(not item for item in normalized):
            raise ValueError("capability_ceiling cannot contain blank values")
        return normalized

    @model_validator(mode="after")
    def validate_request(self) -> ExecutionAuthorityRevalidationRequest:
        if self.attempt_number != self.prior_snapshot.attempt_number:
            raise ValueError("revalidation attempt number does not match prior snapshot")
        if self.scope != self.prior_snapshot.scope:
            raise ValueError("revalidation scope does not match prior snapshot")
        if not self.scope.allows_session(self.session_id):
            raise ValueError("authority scope does not allow this session")
        if self.authority_grant is not None and self.authority_grant.scope != self.scope:
            raise ValueError("authority grant scope does not match revalidation scope")
        return self


class ExecutionAuthorityRevalidation(BaseModel):
    """Durable outcome of rechecking one existing Attempt's authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_number: int = Field(ge=1)
    prior_snapshot_digest: str = Field(min_length=64, max_length=64)
    source_authority_digest: str = Field(min_length=64, max_length=71)
    effective_snapshot_digest: str | None = Field(default=None, min_length=64, max_length=64)
    decision: ExecutionAuthorityDecision
    validated_at: datetime
    expires_at: datetime | None = None
    reason_code: str | None = Field(default=None, max_length=256)
    effective_snapshot: ExecutionAuthoritySnapshot | None = None

    @field_validator(
        "prior_snapshot_digest",
        "source_authority_digest",
        "effective_snapshot_digest",
    )
    @classmethod
    def normalize_digest_fields(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return normalize_digest(value, field_name=info.field_name)

    @field_validator("validated_at", "expires_at")
    @classmethod
    def normalize_optional_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("revalidation timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("reason_code")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason_code must not be blank when provided")
        reject_secret_material(normalized)
        return normalized

    @model_validator(mode="after")
    def validate_decision_shape(self) -> ExecutionAuthorityRevalidation:
        if self.decision in {
            ExecutionAuthorityDecision.ALLOWED,
            ExecutionAuthorityDecision.NARROWED,
        } and (self.effective_snapshot_digest is None or self.effective_snapshot is None):
            raise ValueError("accepted revalidation requires recoverable effective_snapshot")
        if (
            self.effective_snapshot is not None
            and self.effective_snapshot.snapshot_digest != self.effective_snapshot_digest
        ):
            raise ValueError("effective snapshot digest does not match revalidation evidence")
        if (
            self.decision
            in {
                ExecutionAuthorityDecision.DENIED,
                ExecutionAuthorityDecision.EXPIRED,
                ExecutionAuthorityDecision.REVOKED,
            }
            and not self.reason_code
        ):
            raise ValueError("rejected revalidation requires reason_code")
        return self

    def to_event_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
