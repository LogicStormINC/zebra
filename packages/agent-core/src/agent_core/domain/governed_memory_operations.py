from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from agent_core.domain.events import EventActor, SessionEvent
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryCreate,
    GovernedMemoryLifecycleMutation,
)
from agent_core.domain.identifiers import MemoryId, SessionId

if TYPE_CHECKING:
    from agent_core.ports.aggregate_mutation import (
        AdministrativeMutationCAS,
        WorkerMutationAuthority,
    )


class GovernedMemoryOperationKind(StrEnum):
    WORKER_CANDIDATES = "worker_candidates"
    ADMINISTRATIVE_REVIEW = "administrative_review"


class GovernedMemoryReviewAction(StrEnum):
    CONFIRM = "confirm"
    EXPIRE = "expire"


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
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _replace_created_ids(value: object, created_ids: dict[str, str]) -> object:
    if isinstance(value, str):
        return created_ids.get(value, value)
    if isinstance(value, list):
        return [_replace_created_ids(item, created_ids) for item in value]
    if isinstance(value, dict):
        return {key: _replace_created_ids(item, created_ids) for key, item in value.items()}
    return value


def _canonical_event(event: SessionEvent, created_ids: dict[str, str]) -> object:
    return _replace_created_ids(
        {
            "session_id": str(event.session_id),
            "event_type": event.event_type.value,
            "payload": event.payload,
            "actor": event.actor.value,
            "causation_id": (None if event.causation_id is None else str(event.causation_id)),
            "correlation_id": (None if event.correlation_id is None else str(event.correlation_id)),
            "idempotency_key": event.idempotency_key,
            "policy_version": event.policy_version,
            "model_profile": event.model_profile,
        },
        created_ids,
    )


def _canonical_lifecycle_mutation(
    mutation: GovernedMemoryLifecycleMutation,
    created_ids: dict[str, str],
) -> object:
    return _replace_created_ids(
        mutation.model_dump(mode="json", exclude={"updated_at"}),
        created_ids,
    )


def canonical_worker_memory_mutation_hash(
    *,
    deployment_namespace: str,
    operation_id: str,
    session_id: SessionId,
    expected_stream_revision: int,
    creations: tuple[GovernedMemoryCreate, ...],
    lifecycle_mutations: tuple[GovernedMemoryLifecycleMutation, ...],
    events: tuple[SessionEvent, ...],
) -> str:
    created_ids = {
        str(item.record.memory_id): f"creation:{item.creation_key}" for item in creations
    }
    creation_payloads = [
        {"creation_key": item.creation_key, "content_digest": item.content_digest}
        for item in creations
    ]
    return _hash(
        {
            "deployment_namespace": _text(deployment_namespace, field_name="deployment_namespace"),
            "operation_id": _text(operation_id, field_name="operation_id"),
            "session_id": str(session_id),
            "expected_stream_revision": expected_stream_revision,
            "creations": creation_payloads,
            "lifecycle_mutations": [
                _canonical_lifecycle_mutation(item, created_ids) for item in lifecycle_mutations
            ],
            "events": [_canonical_event(event, created_ids) for event in events],
        }
    )


class WorkerMemoryMutationPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: str = Field(max_length=255)
    session_id: SessionId
    expected_stream_revision: int = Field(ge=-1)
    request_digest: str
    creations: tuple[GovernedMemoryCreate, ...] = Field(default=(), max_length=500)
    lifecycle_mutations: tuple[GovernedMemoryLifecycleMutation, ...] = Field(
        default=(), max_length=500
    )
    events: tuple[SessionEvent, ...] = Field(default=(), max_length=1000)

    @field_validator("operation_id")
    @classmethod
    def require_operation_id(cls, value: str) -> str:
        return _text(value, field_name="operation_id")

    @field_validator("request_digest")
    @classmethod
    def require_request_digest(cls, value: str) -> str:
        return _digest(value, field_name="request_digest")

    @model_validator(mode="after")
    def reject_noop_aggregate(self) -> Self:
        if not self.events or not (self.creations or self.lifecycle_mutations):
            raise ValueError("Worker Memory aggregate requires mutations and Events")
        return self
    @classmethod
    def create(
        cls,
        *,
        deployment_namespace: str,
        operation_id: str,
        session_id: SessionId,
        expected_stream_revision: int,
        creations: tuple[GovernedMemoryCreate, ...] = (),
        lifecycle_mutations: tuple[GovernedMemoryLifecycleMutation, ...] = (),
        events: tuple[SessionEvent, ...] = (),
    ) -> WorkerMemoryMutationPlan:
        return cls(
            operation_id=operation_id,
            session_id=session_id,
            expected_stream_revision=expected_stream_revision,
            request_digest=canonical_worker_memory_mutation_hash(
                deployment_namespace=deployment_namespace,
                operation_id=operation_id,
                session_id=session_id,
                expected_stream_revision=expected_stream_revision,
                creations=creations,
                lifecycle_mutations=lifecycle_mutations,
                events=events,
            ),
            creations=creations,
            lifecycle_mutations=lifecycle_mutations,
            events=events,
        )

    def validate_for(
        self,
        deployment_namespace: str,
        authority: WorkerMutationAuthority,
    ) -> Self:
        if deployment_namespace != authority.deployment_namespace:
            raise GovernedMemoryConflictError("Worker Memory namespace does not match authority")
        if (
            self.session_id != authority.session_id
            or self.expected_stream_revision != authority.expected_stream_revision
        ):
            raise GovernedMemoryConflictError("Worker Memory plan does not match authority CAS")
        for creation in self.creations:
            creation.validate_canonical()
        if any(event.session_id != self.session_id for event in self.events):
            raise GovernedMemoryConflictError("Worker Memory Event does not match plan session")
        expected_digest = canonical_worker_memory_mutation_hash(
            deployment_namespace=deployment_namespace,
            operation_id=self.operation_id,
            session_id=self.session_id,
            expected_stream_revision=self.expected_stream_revision,
            creations=self.creations,
            lifecycle_mutations=self.lifecycle_mutations,
            events=self.events,
        )
        if self.request_digest != expected_digest:
            raise GovernedMemoryConflictError("Worker Memory request digest mismatch")
        return self


def canonical_administrative_memory_review_hash(
    *, deployment_namespace: str, request: AdministrativeMemoryReviewRequest
) -> str:
    return _hash(
        {
            "deployment_namespace": _text(deployment_namespace, field_name="deployment_namespace"),
            "review": request.model_dump(mode="json", exclude={"request_digest", "created_at"}),
        }
    )


class AdministrativeMemoryReviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: str = Field(max_length=255)
    request_digest: str
    session_id: SessionId
    expected_stream_revision: int = Field(ge=-1)
    memory_id: MemoryId
    expected_revision: int = Field(ge=1)
    action: GovernedMemoryReviewAction
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
        return _digest(value, field_name="request_digest")

    @field_validator("created_at")
    @classmethod
    def require_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @classmethod
    def create(
        cls,
        *,
        deployment_namespace: str,
        operation_id: str,
        session_id: SessionId,
        expected_stream_revision: int,
        memory_id: MemoryId,
        expected_revision: int,
        action: GovernedMemoryReviewAction,
        operator: str,
        reason: str,
        created_at: datetime,
        actor: EventActor = EventActor.USER,
    ) -> AdministrativeMemoryReviewRequest:
        request = cls(
            operation_id=operation_id,
            request_digest="0" * 64,
            session_id=session_id,
            expected_stream_revision=expected_stream_revision,
            memory_id=memory_id,
            expected_revision=expected_revision,
            action=action,
            operator=operator,
            reason=reason,
            actor=actor,
            created_at=created_at,
        )
        return request.model_copy(
            update={
                "request_digest": canonical_administrative_memory_review_hash(
                    deployment_namespace=deployment_namespace,
                    request=request,
                )
            }
        )

    def validate_for(
        self,
        deployment_namespace: str,
        authority: AdministrativeMutationCAS,
    ) -> Self:
        if deployment_namespace != authority.deployment_namespace:
            raise GovernedMemoryConflictError("review namespace does not match authority")
        if (
            self.session_id != authority.session_id
            or self.expected_stream_revision != authority.expected_stream_revision
        ):
            raise GovernedMemoryConflictError("administrative review does not match authority CAS")
        expected_digest = canonical_administrative_memory_review_hash(
            deployment_namespace=deployment_namespace,
            request=self,
        )
        if self.request_digest != expected_digest:
            raise GovernedMemoryConflictError("administrative review digest mismatch")
        return self
