from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)


class GovernedMemoryConflictError(ValueError):
    """An idempotency key or expected revision no longer has the requested meaning."""


class GovernedMemoryStateError(ValueError):
    """A governed Memory lifecycle transition is invalid."""


def _canonical_text(value: str, *, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and trimmed")
    return value


def _digest(value: str, *, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_governed_memory_content_hash(record: MemoryRecord) -> str:
    """Hash semantic content and immutable provenance, excluding lifecycle state."""

    return _canonical_hash(
        {
            "memory_type": record.memory_type.value,
            "text": record.text,
            "confidence": record.confidence,
            "visibility": record.visibility.value,
            "tenant_id": record.tenant_id,
            "user_id": record.user_id,
            "repo_id": record.repo_id,
            "source_session_id": (
                None if record.source_session_id is None else str(record.source_session_id)
            ),
            "source_event_start": record.source_event_start,
            "source_event_end": record.source_event_end,
            "source_commit_sha": record.source_commit_sha,
            "expires_at": (None if record.expires_at is None else record.expires_at.isoformat()),
        }
    )


def canonical_governed_memory_creation_key(record: MemoryRecord) -> str:
    """Stable retry identity independent of a regenerated public Memory ID."""

    return _canonical_hash(
        {
            "content_digest": canonical_governed_memory_content_hash(record),
            "source_session_id": (
                None if record.source_session_id is None else str(record.source_session_id)
            ),
            "source_event_start": record.source_event_start,
            "source_event_end": record.source_event_end,
        }
    )


class GovernedMemoryEntry(BaseModel):
    """Authoritative readable Memory state; deleted state uses a tombstone instead."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: str = Field(max_length=255)
    record: MemoryRecord
    revision: int = Field(ge=1)
    creation_key: str = Field(max_length=255)
    content_digest: str

    @field_validator("deployment_namespace", "creation_key")
    @classmethod
    def require_canonical_text(cls, value: str, info: ValidationInfo) -> str:
        return _canonical_text(value, field_name=info.field_name or "text")

    @field_validator("content_digest")
    @classmethod
    def require_content_digest(cls, value: str) -> str:
        return _digest(value, field_name="content_digest")

    @model_validator(mode="after")
    def reject_deleted_record(self) -> Self:
        if self.record.status is MemoryStatus.DELETED:
            raise ValueError("deleted Memory must be represented by a tombstone")
        if self.record.updated_at < self.record.created_at:
            raise ValueError("Memory updated_at must not predate created_at")
        if self.creation_key != canonical_governed_memory_creation_key(self.record):
            raise GovernedMemoryConflictError("creation_key does not match Memory record")
        if self.content_digest != canonical_governed_memory_content_hash(self.record):
            raise GovernedMemoryConflictError("content_digest does not match Memory record")
        return self


class GovernedMemoryManagementContext(BaseModel):
    """Audit identity for content-free authority inspection and rebuild scans."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: str = Field(max_length=255)
    operator: str = Field(max_length=255)
    reason: str = Field(max_length=2000)

    @field_validator("operation_id", "operator", "reason")
    @classmethod
    def require_canonical_text(cls, value: str, info: ValidationInfo) -> str:
        return _canonical_text(value, field_name=info.field_name or "text")


class GovernedMemoryTombstone(BaseModel):
    """Content-free retained authority for a deleted Memory identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: str = Field(max_length=255)
    memory_id: MemoryId
    revision: int = Field(ge=1)
    memory_type: MemoryType
    visibility: MemoryVisibility
    tenant_id: str | None = None
    user_id: str | None = None
    repo_id: str | None = None
    provenance_digest: str
    created_at: datetime
    updated_at: datetime
    status: MemoryStatus = MemoryStatus.DELETED

    @field_validator("deployment_namespace")
    @classmethod
    def require_namespace(cls, value: str) -> str:
        return _canonical_text(value, field_name="deployment_namespace")

    @field_validator("provenance_digest")
    @classmethod
    def require_provenance_digest(cls, value: str) -> str:
        return _digest(value, field_name="provenance_digest")

    @model_validator(mode="after")
    def require_tombstone_shape(self) -> Self:
        if self.status is not MemoryStatus.DELETED:
            raise ValueError("tombstone status must be deleted")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("tombstone timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("tombstone updated_at must not predate created_at")
        required_scope = {
            MemoryVisibility.REPO: self.repo_id,
            MemoryVisibility.USER: self.user_id,
            MemoryVisibility.TENANT: self.tenant_id,
        }[self.visibility]
        if not required_scope or required_scope != required_scope.strip():
            raise ValueError("tombstone visibility requires its canonical scope")
        return self


class GovernedMemoryCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record: MemoryRecord
    creation_key: str = Field(max_length=255)
    content_digest: str

    @field_validator("creation_key")
    @classmethod
    def require_creation_key(cls, value: str) -> str:
        return _canonical_text(value, field_name="creation_key")

    @field_validator("content_digest")
    @classmethod
    def require_content_digest(cls, value: str) -> str:
        return _digest(value, field_name="content_digest")

    @model_validator(mode="after")
    def require_candidate(self) -> Self:
        if self.record.status is not MemoryStatus.CANDIDATE:
            raise ValueError("governed Memory creation requires candidate status")
        self.validate_canonical()
        return self

    def validate_canonical(self) -> Self:
        if self.creation_key != canonical_governed_memory_creation_key(self.record):
            raise GovernedMemoryConflictError("creation_key does not match Memory candidate")
        if self.content_digest != canonical_governed_memory_content_hash(self.record):
            raise GovernedMemoryConflictError("content_digest does not match Memory candidate")
        return self

    @classmethod
    def from_candidate(cls, record: MemoryRecord) -> GovernedMemoryCreate:
        return cls(
            record=record,
            creation_key=canonical_governed_memory_creation_key(record),
            content_digest=canonical_governed_memory_content_hash(record),
        )


_ALLOWED_TRANSITIONS = {
    MemoryStatus.CANDIDATE: frozenset(
        {MemoryStatus.CONFIRMED, MemoryStatus.EXPIRED, MemoryStatus.DELETED}
    ),
    MemoryStatus.CONFIRMED: frozenset(
        {MemoryStatus.SUPERSEDED, MemoryStatus.EXPIRED, MemoryStatus.DELETED}
    ),
    MemoryStatus.SUPERSEDED: frozenset({MemoryStatus.DELETED}),
    MemoryStatus.EXPIRED: frozenset({MemoryStatus.DELETED}),
    MemoryStatus.DELETED: frozenset(),
}


class GovernedMemoryLifecycleMutation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_id: MemoryId
    expected_revision: int = Field(ge=1)
    previous_status: MemoryStatus
    status: MemoryStatus
    superseded_by: MemoryId | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def require_valid_transition(self) -> Self:
        if self.updated_at.tzinfo is None:
            raise ValueError("Memory mutation updated_at must be timezone-aware")
        if self.status not in _ALLOWED_TRANSITIONS[self.previous_status]:
            raise GovernedMemoryStateError(
                f"invalid Memory transition: {self.previous_status} -> {self.status}"
            )
        if (self.status is MemoryStatus.SUPERSEDED) != (self.superseded_by is not None):
            raise ValueError("only superseded mutation requires superseded_by")
        if self.superseded_by == self.memory_id:
            raise ValueError("Memory cannot supersede itself")
        return self

    @classmethod
    def from_status_update(
        cls,
        record: MemoryRecord,
        *,
        previous_status: MemoryStatus,
        expected_revision: int,
    ) -> GovernedMemoryLifecycleMutation:
        return cls(
            memory_id=record.memory_id,
            expected_revision=expected_revision,
            previous_status=previous_status,
            status=record.status,
            superseded_by=record.superseded_by,
            updated_at=record.updated_at,
        )
