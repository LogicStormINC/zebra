from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from agent_core.domain.events import EventActor
from agent_core.domain.governed_memories import GovernedMemoryConflictError, GovernedMemoryCreate
from agent_core.domain.identifiers import SessionId
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS


def _text(value: str, *, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and trimmed")
    return value


def _digest(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("request_digest must be a lowercase sha256 digest")
    return value


def canonical_administrative_memory_creation_hash(
    *, deployment_namespace: str, request: AdministrativeMemoryCreationRequest
) -> str:
    payload = {
        "deployment_namespace": _text(deployment_namespace, field_name="deployment_namespace"),
        "creation": request.model_dump(mode="json", exclude={"request_digest", "created_at"}),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class AdministrativeMemoryCreationRequest(BaseModel):
    """Atomically create and confirm one explicit user-authored Memory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: str = Field(max_length=255)
    request_digest: str
    session_id: SessionId
    expected_stream_revision: int = Field(ge=-1)
    memory: GovernedMemoryCreate
    operator: str = Field(max_length=255)
    reason: str = Field(max_length=2000)
    actor: EventActor = EventActor.USER
    created_at: datetime

    @field_validator("operation_id", "operator", "reason")
    @classmethod
    def require_canonical_text(cls, value: str, info: ValidationInfo) -> str:
        return _text(value, field_name=info.field_name or "text")

    @field_validator("request_digest")
    @classmethod
    def require_request_digest(cls, value: str) -> str:
        return _digest(value)

    @model_validator(mode="after")
    def require_creation_provenance(self) -> Self:
        record = self.memory.record
        if record.source_session_id != self.session_id:
            raise ValueError("created Memory must use the audit Session")
        if record.source_event_start is None or record.source_event_end is None:
            raise ValueError("created Memory must retain source Event provenance")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return self

    @classmethod
    def create(
        cls,
        *,
        deployment_namespace: str,
        operation_id: str,
        session_id: SessionId,
        expected_stream_revision: int,
        memory: GovernedMemoryCreate,
        operator: str,
        reason: str,
        created_at: datetime,
        actor: EventActor = EventActor.USER,
    ) -> AdministrativeMemoryCreationRequest:
        request = cls(
            operation_id=operation_id,
            request_digest="0" * 64,
            session_id=session_id,
            expected_stream_revision=expected_stream_revision,
            memory=memory,
            operator=operator,
            reason=reason,
            actor=actor,
            created_at=created_at,
        )
        return request.model_copy(
            update={
                "request_digest": canonical_administrative_memory_creation_hash(
                    deployment_namespace=deployment_namespace, request=request
                )
            }
        )

    def validate_for(self, deployment_namespace: str, authority: AdministrativeMutationCAS) -> Self:
        if deployment_namespace != authority.deployment_namespace:
            raise GovernedMemoryConflictError("creation namespace does not match authority")
        if self.session_id != authority.session_id or (
            self.expected_stream_revision != authority.expected_stream_revision
        ):
            raise GovernedMemoryConflictError("creation does not match authority CAS")
        self.memory.validate_canonical()
        expected = canonical_administrative_memory_creation_hash(
            deployment_namespace=deployment_namespace, request=self
        )
        if self.request_digest != expected:
            raise GovernedMemoryConflictError("creation digest mismatch")
        return self
