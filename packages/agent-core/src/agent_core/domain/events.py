from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import (
    CorrelationId,
    EventId,
    SessionId,
    new_event_id,
)


class EventType(StrEnum):
    SESSION_CREATED = "session_created"
    SESSION_TITLE_UPDATED = "session_title_updated"
    USER_MESSAGE_RECEIVED = "user_message_received"
    TASK_PREPARED = "task_prepared"
    RUNTIME_PROVISIONED = "runtime_provisioned"
    PLAN_PROPOSED = "plan_proposed"
    PLAN_APPROVED = "plan_approved"
    PLAN_UPDATED = "plan_updated"
    MODEL_REQUEST_STARTED = "model_request_started"
    MODEL_RESPONSE_DELTA = "model_response_delta"
    MODEL_RESPONSE_RECEIVED = "model_response_received"
    CONTEXT_COMPACTED = "context_compacted"
    CONTEXT_COMPACTION_REJECTED = "context_compaction_rejected"
    CONTEXT_CAPSULE_CREATED = "context_capsule_created"
    CONTEXT_CONTINUATION_SELECTED = "context_continuation_selected"
    SESSION_HANDOFF_COMMITTED = "session_handoff_committed"
    SESSION_HANDOFF_RECEIVED = "session_handoff_received"
    SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED = "session_handoff_workspace_drift_detected"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    SUBAGENT_FAILED = "subagent_failed"
    SUBAGENT_CANCELLED = "subagent_cancelled"
    HARNESS_ATTEMPT_STARTED = "harness_attempt_started"
    TOOL_CALL_PROPOSED = "tool_call_proposed"
    POLICY_DECISION_MADE = "policy_decision_made"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    CLARIFICATION_REQUESTED = "clarification_requested"
    CLARIFICATION_RESPONDED = "clarification_responded"
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_COMPLETED = "tool_execution_completed"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    PATCH_APPLIED = "patch_applied"
    TESTS_COMPLETED = "tests_completed"
    MEMORY_CANDIDATE_EXTRACTED = "memory_candidate_extracted"
    MEMORY_REVIEW_RECORDED = "memory_review_recorded"
    SESSION_SUSPENDED = "session_suspended"
    SESSION_RESUMED = "session_resumed"
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"
    SESSION_CANCELLED = "session_cancelled"


class EventActor(StrEnum):
    USER = "user"
    HARNESS = "harness"
    POLICY = "policy"
    TOOL = "tool"
    SYSTEM = "system"


class SessionEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: EventId
    session_id: SessionId
    sequence: int = Field(ge=0)
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: EventActor
    created_at: datetime
    causation_id: EventId | None = None
    correlation_id: CorrelationId | None = None
    idempotency_key: str | None = None
    policy_version: str | None = None
    model_profile: str | None = None

    @field_validator("created_at")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @classmethod
    def create(
        cls,
        *,
        session_id: SessionId,
        sequence: int,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, Any] | None = None,
        causation_id: EventId | None = None,
        correlation_id: CorrelationId | None = None,
        idempotency_key: str | None = None,
        policy_version: str | None = None,
        model_profile: str | None = None,
        created_at: datetime | None = None,
    ) -> "SessionEvent":
        normalized_payload = payload or {}
        try:
            from agent_core.contracts.events import validate_event_payload

            normalized_payload = validate_event_payload(event_type, normalized_payload)
        except KeyError:
            pass
        return cls(
            event_id=new_event_id(),
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            payload=normalized_payload,
            actor=actor,
            created_at=created_at or datetime.now(UTC),
            causation_id=causation_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            policy_version=policy_version,
            model_profile=model_profile,
        )
