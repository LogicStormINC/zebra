from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult


class EffectDispatchStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    FAILED_NO_EFFECT = "failed_no_effect"
    UNCERTAIN = "uncertain"
    DEAD_LETTER = "dead_letter"


class EffectResolutionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED_NO_EFFECT = "failed_no_effect"


class EffectDispatchConflictError(ValueError):
    """Raised when an idempotency identity is reused with different meaning."""


class EffectDispatchStateError(ValueError):
    """Raised when an Effect dispatch transition is not allowed."""


class EffectEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason_code: str = Field(max_length=128)
    detail: str | None = Field(default=None, max_length=1024)
    provider_operation_id_hash: str | None = Field(default=None, max_length=64)
    artifact_ref: str | None = Field(default=None, max_length=2048)

    @field_validator("reason_code")
    @classmethod
    def require_reason_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("effect evidence reason_code must not be blank")
        return value

    @field_validator("detail", "provider_operation_id_hash", "artifact_ref")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("effect evidence fields must not be blank when set")
        return value

    @field_validator("provider_operation_id_hash")
    @classmethod
    def require_provider_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("provider_operation_id_hash must be a sha256 hex digest")
        return value


class EffectScheduleRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    root_session_id: SessionId
    identity: EffectIdentity
    request_hash: str
    payload_artifact_ref: str = Field(max_length=2048)
    started_event: SessionEvent

    @field_validator("request_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("request_hash must be a sha256 hex digest")
        return value

    @field_validator("payload_artifact_ref")
    @classmethod
    def require_artifact_ref(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("payload_artifact_ref must not be blank")
        return value

    @model_validator(mode="after")
    def require_started_event(self) -> Self:
        if self.started_event.event_type is not EventType.TOOL_EXECUTION_STARTED:
            raise ValueError("started_event must be TOOL_EXECUTION_STARTED")
        return self

    @property
    def execution_session_id(self) -> SessionId:
        return self.started_event.session_id

    @property
    def ledger_key(self) -> str:
        return self.identity.ledger_key()


class EffectDispatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dispatch_id: UUID
    execution_session_id: SessionId
    root_session_id: SessionId
    identity: EffectIdentity
    attempt: int = Field(ge=1)
    request_hash: str
    payload_artifact_ref: str
    status: EffectDispatchStatus
    intent_event_id: EventId
    terminal_event_id: EventId | None = None
    result: ToolResult | None = None
    evidence: EffectEvidence | None = None
    evidence_history: tuple[EffectEvidence, ...] = ()
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("effect dispatch timestamps must be timezone-aware")
        return value

    @field_validator("request_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        return EffectScheduleRequest.require_sha256(value)

    @field_validator("payload_artifact_ref")
    @classmethod
    def require_artifact_ref(cls, value: str) -> str:
        return EffectScheduleRequest.require_artifact_ref(value)

    @model_validator(mode="after")
    def require_terminal_shape(self) -> Self:
        terminal_required = self.status in {
            EffectDispatchStatus.SUCCEEDED,
            EffectDispatchStatus.FAILED_NO_EFFECT,
            EffectDispatchStatus.DEAD_LETTER,
        }
        terminal_forbidden = self.status in {
            EffectDispatchStatus.PENDING,
            EffectDispatchStatus.CLAIMED,
        }
        if terminal_required and self.terminal_event_id is None:
            raise ValueError("terminal dispatch state requires terminal_event_id")
        if terminal_forbidden and self.terminal_event_id is not None:
            raise ValueError("non-terminal dispatch state cannot carry terminal_event_id")
        if (self.status is EffectDispatchStatus.SUCCEEDED) != (self.result is not None):
            raise ValueError("only succeeded dispatches carry a ToolResult")
        if self.result is not None and self.result.status is not ToolCallStatus.EXECUTED:
            raise ValueError("succeeded dispatch ToolResult must be executed")
        evidence_required = self.status in {
            EffectDispatchStatus.FAILED_NO_EFFECT,
            EffectDispatchStatus.UNCERTAIN,
            EffectDispatchStatus.DEAD_LETTER,
        }
        if evidence_required and self.evidence is None:
            raise ValueError("failure and uncertain dispatch states require evidence")
        if terminal_forbidden and self.evidence is not None:
            raise ValueError("pending and claimed dispatches cannot carry evidence")
        if self.evidence_history and self.evidence_history[-1] != self.evidence:
            raise ValueError("latest evidence must end the evidence history")
        if terminal_forbidden and self.evidence_history:
            raise ValueError("pending and claimed dispatches cannot carry evidence history")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self

    @property
    def ledger_key(self) -> str:
        return self.identity.ledger_key()


class EffectClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dispatch: EffectDispatch
    claim_fence: LeaseFence
    claim_expires_at: datetime

    @field_validator("claim_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("claim_expires_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_claimed_dispatch(self) -> Self:
        if self.dispatch.status is not EffectDispatchStatus.CLAIMED:
            raise ValueError("effect claim requires a claimed dispatch")
        if self.claim_expires_at <= self.dispatch.updated_at:
            raise ValueError("effect claim expiry must follow dispatch update time")
        return self
