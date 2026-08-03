from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
    AgentReleaseId,
)

MAX_AGENT_REFERENCE_LENGTH = 512
MAX_DEFINITION_NAME_LENGTH = 256
MAX_DEFINITION_DESCRIPTION_LENGTH = 4_096
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_PATTERN = re.compile(
    r"^[a-z][a-z0-9-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)+@[A-Za-z0-9][A-Za-z0-9._-]*$"
)
_REQUIRED_REFERENCE_FIELDS = (
    "model_policy_ref",
    "tool_profile_ref",
    "memory_policy_ref",
    "security_policy_ref",
    "evaluation_profile_ref",
    "runtime_profile_ref",
)
_FORBIDDEN_REFERENCE_TERMS = (
    "api-key",
    "apikey",
    "credential",
    "password",
    "secret",
    "token",
    "code",
    "exec",
    "javascript",
    "python",
    "script",
    "shell",
)


class AgentReleaseStatus(StrEnum):
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"


class AgentReleaseTransitionError(ValueError):
    """Raised when a Release attempts an invalid lifecycle transition."""


class AgentDefinitionScope(BaseModel):
    """Opaque authority scope for one Definition metadata aggregate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authority_issuer: str = Field(min_length=1, max_length=2_048)
    namespace_id: str = Field(min_length=1, max_length=255)
    definition_id: AgentDefinitionId

    @field_validator("authority_issuer", "namespace_id")
    @classmethod
    def require_trimmed_scope_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Definition scope values must not be blank")
        return value

    @property
    def scope_key(self) -> tuple[str, str, AgentDefinitionId]:
        return self.authority_issuer, self.namespace_id, self.definition_id

    def require_match(self, other: AgentDefinitionScope) -> None:
        if self != other:
            raise ValueError("Definition scope mismatch")


class AgentDefinition(BaseModel):
    """Immutable logical Definition metadata; it is not an execution identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_id: AgentDefinitionId
    authority_issuer: str = Field(min_length=1, max_length=2_048)
    namespace_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=MAX_DEFINITION_NAME_LENGTH)
    description: str = Field(default="", max_length=MAX_DEFINITION_DESCRIPTION_LENGTH)
    revision: int = Field(default=0, ge=0)
    created_at: datetime

    @field_validator("authority_issuer", "namespace_id", "name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _required_or_empty(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("created_at")
    @classmethod
    def require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @property
    def scope(self) -> AgentDefinitionScope:
        return AgentDefinitionScope(
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
            definition_id=self.definition_id,
        )


class AgentDefinitionVersion(BaseModel):
    """Immutable, digest-bound Definition configuration Version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version_id: AgentDefinitionVersionId
    definition_id: AgentDefinitionId
    authority_issuer: str = Field(min_length=1, max_length=2_048)
    namespace_id: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=1)
    schema_version: str = Field(default="agent-definition/1", max_length=64)
    model_policy_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    tool_profile_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    skill_snapshot_digest: str
    memory_policy_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    security_policy_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    evaluation_profile_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    runtime_profile_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    definition_digest: str | None = None
    created_at: datetime

    @field_validator("authority_issuer", "namespace_id")
    @classmethod
    def normalize_scope_text(cls, value: str) -> str:
        return _required_or_empty(value)

    @field_validator("schema_version")
    @classmethod
    def require_schema_version(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"agent-definition/[1-9][0-9]*", value):
            raise ValueError("schema_version must use agent-definition/<positive integer>")
        return value

    @field_validator(*_REQUIRED_REFERENCE_FIELDS)
    @classmethod
    def require_versioned_reference(cls, value: str) -> str:
        return _validate_reference(value)

    @field_validator("skill_snapshot_digest", "definition_digest", mode="before")
    @classmethod
    def normalize_digest(cls, value: str | None) -> str | None:
        return _normalize_digest(value, allow_none=True)

    @field_validator("created_at")
    @classmethod
    def require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        expected = canonical_agent_definition_digest(self)
        if self.definition_digest is not None and self.definition_digest != expected:
            raise ValueError("definition_digest does not match immutable Version content")
        object.__setattr__(self, "definition_digest", expected)
        return self

    @classmethod
    def from_definition(
        cls,
        definition: AgentDefinition,
        *,
        version_id: AgentDefinitionVersionId,
        version: int,
        created_at: datetime,
        model_policy_ref: str,
        tool_profile_ref: str,
        skill_snapshot_digest: str,
        memory_policy_ref: str,
        security_policy_ref: str,
        evaluation_profile_ref: str,
        runtime_profile_ref: str,
        definition_digest: str | None = None,
    ) -> Self:
        return cls(
            version_id=version_id,
            definition_id=definition.definition_id,
            authority_issuer=definition.authority_issuer,
            namespace_id=definition.namespace_id,
            version=version,
            created_at=created_at,
            model_policy_ref=model_policy_ref,
            tool_profile_ref=tool_profile_ref,
            skill_snapshot_digest=skill_snapshot_digest,
            memory_policy_ref=memory_policy_ref,
            security_policy_ref=security_policy_ref,
            evaluation_profile_ref=evaluation_profile_ref,
            runtime_profile_ref=runtime_profile_ref,
            definition_digest=definition_digest,
        )

    @property
    def scope(self) -> AgentDefinitionScope:
        return AgentDefinitionScope(
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
            definition_id=self.definition_id,
        )

    @property
    def ordering_key(self) -> tuple[int, str]:
        """Stable ordering for versions in one Definition scope."""

        return self.version, str(self.version_id)


class AgentRelease(BaseModel):
    """Append-only Release state for one Definition Version and environment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    release_id: AgentReleaseId
    definition_id: AgentDefinitionId
    version_id: AgentDefinitionVersionId
    authority_issuer: str = Field(min_length=1, max_length=2_048)
    namespace_id: str = Field(min_length=1, max_length=255)
    environment: str = Field(min_length=1, max_length=128)
    status: AgentReleaseStatus
    revision: int = Field(ge=1)
    definition_digest: str
    actor_ref: str = Field(min_length=1, max_length=512)
    reason_class: str | None = Field(default=None, max_length=128)
    effective_at: datetime

    @field_validator("authority_issuer", "namespace_id", "environment", "actor_ref")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return _required_or_empty(value)

    @field_validator("reason_class")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("definition_digest", mode="before")
    @classmethod
    def normalize_definition_digest(cls, value: str) -> str:
        normalized = _normalize_digest(value)
        assert normalized is not None
        return normalized

    @field_validator("effective_at")
    @classmethod
    def require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("effective_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_lifecycle_shape(self) -> Self:
        if self.status is not AgentReleaseStatus.PUBLISHED and self.reason_class is None:
            raise ValueError("deprecated and revoked Releases require reason_class")
        return self

    @classmethod
    def from_version(
        cls,
        version: AgentDefinitionVersion,
        *,
        release_id: AgentReleaseId,
        environment: str,
        actor_ref: str,
        effective_at: datetime,
        revision: int = 1,
    ) -> Self:
        if version.definition_digest is None:
            raise ValueError("Definition Version must have a digest")
        return cls(
            release_id=release_id,
            definition_id=version.definition_id,
            version_id=version.version_id,
            authority_issuer=version.authority_issuer,
            namespace_id=version.namespace_id,
            environment=environment,
            status=AgentReleaseStatus.PUBLISHED,
            revision=revision,
            definition_digest=version.definition_digest,
            actor_ref=actor_ref,
            effective_at=effective_at,
        )

    def transition(
        self,
        status: AgentReleaseStatus,
        *,
        revision: int,
        actor_ref: str,
        reason_class: str,
        effective_at: datetime,
    ) -> Self:
        allowed = {
            AgentReleaseStatus.PUBLISHED: {
                AgentReleaseStatus.DEPRECATED,
                AgentReleaseStatus.REVOKED,
            },
            AgentReleaseStatus.DEPRECATED: {AgentReleaseStatus.REVOKED},
            AgentReleaseStatus.REVOKED: set(),
        }
        if status not in allowed[self.status]:
            raise AgentReleaseTransitionError(
                f"cannot transition Release from {self.status} to {status}"
            )
        if revision != self.revision + 1:
            raise AgentReleaseTransitionError("Release revision must increase by one")
        return type(self)(
            **{
                **self.model_dump(),
                "status": status,
                "revision": revision,
                "actor_ref": actor_ref,
                "reason_class": reason_class,
                "effective_at": effective_at,
            }
        )


def canonical_agent_definition_digest(version: AgentDefinitionVersion) -> str:
    """Hash only immutable Definition content, never Release or creation metadata."""

    payload: dict[str, Any] = {
        "authority_issuer": version.authority_issuer,
        "definition_id": str(version.definition_id),
        "evaluation_profile_ref": version.evaluation_profile_ref,
        "memory_policy_ref": version.memory_policy_ref,
        "model_policy_ref": version.model_policy_ref,
        "namespace_id": version.namespace_id,
        "runtime_profile_ref": version.runtime_profile_ref,
        "schema_version": version.schema_version,
        "security_policy_ref": version.security_policy_ref,
        "skill_snapshot_digest": version.skill_snapshot_digest,
        "tool_profile_ref": version.tool_profile_ref,
        "version": version.version,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()


def _required_or_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must not be blank")
    return value


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _required_or_empty(value)


def _normalize_digest(value: str | None, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise ValueError("digest must be a sha256 hexadecimal string")
    value = value.strip().lower()
    if value.startswith("sha256:"):
        value = value[7:]
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError("digest must be a lowercase sha256 hexadecimal string")
    return value


def _validate_reference(value: str) -> str:
    value = _required_or_empty(value)
    if not _REFERENCE_PATTERN.fullmatch(value):
        raise ValueError("component references must be versioned stable references")
    lower = value.lower()
    if any(term in lower for term in _FORBIDDEN_REFERENCE_TERMS):
        raise ValueError("component references must not contain credentials or secrets")
    if lower.endswith(("@latest", "@current")):
        raise ValueError("component references must not use moving versions")
    return value
