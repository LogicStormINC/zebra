from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from agent_core.domain.governed_memories import GovernedMemoryConflictError
from agent_core.domain.governed_memory_operations import GovernedMemoryOperationKind
from agent_core.domain.identifiers import EventId, MemoryId
from agent_core.domain.memories import MemoryStatus

GOVERNED_MEMORY_RESULT_SCHEMA = "governed-memory-operation-result/1"


def _text(value: str, *, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and trimmed")
    return value


def _digest(value: str, *, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _hash(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class GovernedMemoryRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    memory_id: MemoryId
    revision: int = Field(ge=1)
    status: MemoryStatus


def canonical_governed_memory_result_hash(
    *,
    operation_id: str,
    operation_kind: GovernedMemoryOperationKind,
    request_digest: str,
    memories: tuple[GovernedMemoryRevision, ...],
    event_ids: tuple[EventId, ...],
    event_sequences: tuple[int, ...],
    anchor_event_start: int,
    anchor_event_end: int,
    session_revision: int,
    projection_revision: int,
) -> str:
    return _hash(
        {
            "schema": GOVERNED_MEMORY_RESULT_SCHEMA,
            "operation_id": _text(operation_id, field_name="operation_id"),
            "operation_kind": operation_kind.value,
            "request_digest": _digest(request_digest, field_name="request_digest"),
            "memories": [memory.model_dump(mode="json") for memory in memories],
            "event_ids": [str(event_id) for event_id in event_ids],
            "event_sequences": event_sequences,
            "anchor_event_start": anchor_event_start,
            "anchor_event_end": anchor_event_end,
            "session_revision": session_revision,
            "projection_revision": projection_revision,
        }
    )


class GovernedMemoryOperationReceipt(BaseModel):
    """Bounded, content-free canonical result retained for safe replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: str
    operation_kind: GovernedMemoryOperationKind
    request_digest: str
    result_schema: Literal["governed-memory-operation-result/1"] = (
        "governed-memory-operation-result/1"
    )
    result_digest: str
    memories: tuple[GovernedMemoryRevision, ...] = Field(default=(), max_length=500)
    event_ids: tuple[EventId, ...] = Field(min_length=1, max_length=1000)
    event_sequences: tuple[int, ...] = Field(min_length=1, max_length=1000)
    anchor_event_start: int = Field(ge=0)
    anchor_event_end: int = Field(ge=0)
    session_revision: int = Field(ge=0)
    projection_revision: int = Field(ge=0)
    committed_at: datetime

    @field_validator("operation_id")
    @classmethod
    def require_operation_id(cls, value: str) -> str:
        return _text(value, field_name="operation_id")

    @field_validator("request_digest", "result_digest")
    @classmethod
    def require_digest(cls, value: str, info: ValidationInfo) -> str:
        return _digest(value, field_name=info.field_name or "digest")

    @model_validator(mode="after")
    def require_receipt_shape(self) -> Self:
        if self.committed_at.tzinfo is None:
            raise ValueError("committed_at must be timezone-aware")
        if len(self.event_ids) != len(self.event_sequences):
            raise ValueError("receipt Event IDs and sequences must have equal length")
        expected_sequences = tuple(range(self.anchor_event_start, self.anchor_event_end + 1))
        if self.event_sequences != expected_sequences:
            raise ValueError("receipt Event sequences must be contiguous and match anchor")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("receipt Event IDs must be unique")
        if len({memory.memory_id for memory in self.memories}) != len(self.memories):
            raise ValueError("receipt Memory revisions must be unique")
        if self.session_revision != self.anchor_event_end:
            raise ValueError("receipt Session revision must match anchor end")
        # Both accepted aggregate kinds commit their Event-derived projection at
        # the same anchor; no-op Worker plans are rejected before a receipt exists.
        if self.projection_revision != self.session_revision:
            raise ValueError("receipt Projection revision must match Session revision")
        self.validate_canonical()
        return self

    def validate_canonical(self) -> Self:
        if self.result_schema != GOVERNED_MEMORY_RESULT_SCHEMA:
            raise GovernedMemoryConflictError("Memory operation result schema mismatch")
        expected = canonical_governed_memory_result_hash(
            operation_id=self.operation_id,
            operation_kind=self.operation_kind,
            request_digest=self.request_digest,
            memories=self.memories,
            event_ids=self.event_ids,
            event_sequences=self.event_sequences,
            anchor_event_start=self.anchor_event_start,
            anchor_event_end=self.anchor_event_end,
            session_revision=self.session_revision,
            projection_revision=self.projection_revision,
        )
        if self.result_digest != expected:
            raise GovernedMemoryConflictError("Memory operation result digest mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        operation_kind: GovernedMemoryOperationKind,
        request_digest: str,
        memories: tuple[GovernedMemoryRevision, ...],
        event_ids: tuple[EventId, ...],
        event_sequences: tuple[int, ...],
        anchor_event_start: int,
        anchor_event_end: int,
        session_revision: int,
        projection_revision: int,
        committed_at: datetime,
    ) -> GovernedMemoryOperationReceipt:
        result_digest = canonical_governed_memory_result_hash(
            operation_id=operation_id,
            operation_kind=operation_kind,
            request_digest=request_digest,
            memories=memories,
            event_ids=event_ids,
            event_sequences=event_sequences,
            anchor_event_start=anchor_event_start,
            anchor_event_end=anchor_event_end,
            session_revision=session_revision,
            projection_revision=projection_revision,
        )
        return cls(
            operation_id=operation_id,
            operation_kind=operation_kind,
            request_digest=request_digest,
            result_digest=result_digest,
            memories=memories,
            event_ids=event_ids,
            event_sequences=event_sequences,
            anchor_event_start=anchor_event_start,
            anchor_event_end=anchor_event_end,
            session_revision=session_revision,
            projection_revision=projection_revision,
            committed_at=committed_at,
        )


class GovernedMemoryCommitResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt: GovernedMemoryOperationReceipt
    replayed: bool = False

    @model_validator(mode="after")
    def require_canonical_receipt(self) -> Self:
        self.receipt.validate_canonical()
        return self
