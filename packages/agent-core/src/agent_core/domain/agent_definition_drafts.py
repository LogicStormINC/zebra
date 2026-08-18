"""Mutable Definition draft and append-only validation evidence (ADR-016 §4.1).

A draft is the editing payload under one Definition: it is never referenced by
a Task, grants nothing, does not participate in recovery, uses optimistic
revision CAS, and validation failures only produce validation evidence — never
an immutable Version.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.agent_definitions import (
    _REQUIRED_REFERENCE_FIELDS,
    MAX_AGENT_REFERENCE_LENGTH,
    MAX_DEFINITION_DESCRIPTION_LENGTH,
    MAX_DEFINITION_NAME_LENGTH,
    AgentDefinitionScope,
    _normalize_digest,
    _required_or_empty,
    _validate_reference,
)
from agent_core.domain.identifiers import AgentDefinitionId

MAX_VALIDATION_ISSUES = 64


class AgentDraftValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class AgentDraftValidationIssue(BaseModel):
    """One deterministic static-validation finding on draft content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=512)

    @field_validator("code", "field", "message")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _required_or_empty(value)


class AgentDefinitionDraft(BaseModel):
    """Mutable editing payload; not executable and not Task-referencable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_id: AgentDefinitionId
    authority_issuer: str = Field(min_length=1, max_length=2_048)
    namespace_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=MAX_DEFINITION_NAME_LENGTH)
    description: str = Field(default="", max_length=MAX_DEFINITION_DESCRIPTION_LENGTH)
    model_policy_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    tool_profile_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    skill_snapshot_digest: str
    memory_policy_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    security_policy_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    evaluation_profile_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    runtime_profile_ref: str = Field(max_length=MAX_AGENT_REFERENCE_LENGTH)
    revision: int = Field(default=0, ge=0)
    updated_at: datetime

    @field_validator("authority_issuer", "namespace_id", "name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return _required_or_empty(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator(*_REQUIRED_REFERENCE_FIELDS)
    @classmethod
    def require_versioned_reference(cls, value: str) -> str:
        return _validate_reference(value)

    @field_validator("skill_snapshot_digest")
    @classmethod
    def normalize_digest(cls, value: str) -> str:
        normalized = _normalize_digest(value, allow_none=False)
        assert normalized is not None
        return normalized

    @field_validator("updated_at")
    @classmethod
    def require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        return value

    @property
    def scope(self) -> AgentDefinitionScope:
        return AgentDefinitionScope(
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
            definition_id=self.definition_id,
        )

    @property
    def reference_fields(self) -> tuple[str, ...]:
        return tuple(getattr(self, field) for field in _REQUIRED_REFERENCE_FIELDS)


class AgentDefinitionDraftValidation(BaseModel):
    """Append-only validation evidence; never mutates Version content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_id: AgentDefinitionId
    authority_issuer: str = Field(min_length=1, max_length=2_048)
    namespace_id: str = Field(min_length=1, max_length=255)
    validation_id: UUID
    draft_revision: int = Field(ge=0)
    status: AgentDraftValidationStatus
    issues: tuple[AgentDraftValidationIssue, ...] = Field(
        max_length=MAX_VALIDATION_ISSUES
    )
    evaluated_at: datetime
    evaluator_actor: str = Field(min_length=1, max_length=2_048)

    @field_validator("authority_issuer", "namespace_id", "evaluator_actor")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return _required_or_empty(value)

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_passed_without_issues(self) -> Self:
        if self.status is AgentDraftValidationStatus.PASSED and self.issues:
            raise ValueError("passed validation must not carry issues")
        if self.status is AgentDraftValidationStatus.FAILED and not self.issues:
            raise ValueError("failed validation must carry at least one issue")
        return self

    @property
    def scope(self) -> AgentDefinitionScope:
        return AgentDefinitionScope(
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
            definition_id=self.definition_id,
        )
