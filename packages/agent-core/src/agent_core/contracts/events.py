from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from agent_core.contracts.context_events import (
    ContextCompactedPayload,
    ContextContinuationSelectedPayload,
)
from agent_core.contracts.handoff_events import (
    SessionHandoffCommittedPayload,
    SessionHandoffReceivedPayload,
    SessionHandoffWorkspaceDriftDetectedPayload,
    UserMessageReceivedPayload,
)
from agent_core.contracts.model_events import (
    AttemptContinuationStartedPayload,
    AttemptOutcomeRecordedPayload,
    HarnessAttemptStartedPayload,
    ModelRequestStartedPayload,
    ModelResponseDeltaPayload,
    ModelResponseReceivedPayload,
)
from agent_core.contracts.runtime_events import RuntimeProvisionedPayload
from agent_core.contracts.session_control_events import (
    SessionResumedPayload,
    SessionSuspendedPayload,
)
from agent_core.contracts.task_prepared import TaskPreparedPayload
from agent_core.domain.clarifications import (
    MAX_CLARIFICATION_CHOICE_CHARS,
    MAX_CLARIFICATION_CHOICES,
    MAX_CLARIFICATION_CONTEXT_CHARS,
    MAX_CLARIFICATION_QUESTION_CHARS,
)
from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.events import EventType
from agent_core.domain.plans import MAX_PLAN_STEPS, PlanStep, SessionPlan


class SessionCreatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str

    @field_validator("title")
    @classmethod
    def ensure_title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class SessionTitleUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str

    @field_validator("title")
    @classmethod
    def ensure_title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class PlanUpdatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep] = Field(max_length=MAX_PLAN_STEPS)

    @model_validator(mode="after")
    def validate_complete_plan(self) -> "PlanUpdatedPayload":
        SessionPlan(steps=tuple(self.steps))
        return self


class ToolExecutionCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    tool_name: str
    tool_call_id: str | None = None
    status: str
    output: str
    metadata: dict[str, object]

    @field_validator("attempt_number")
    @classmethod
    def ensure_positive_attempt_number(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("attempt_number must be positive")
        return value

    @field_validator("tool_name", "tool_call_id", "status")
    @classmethod
    def ensure_field_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped


class SubagentLifecyclePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    subagent_id: str
    status: str
    max_model_calls: int
    max_tool_calls: int
    max_depth: int
    model_calls_used: int = 0
    tool_calls_used: int = 0
    source_count: int = 0
    confidence: float = 0.0
    provenance: str

    @field_validator(
        "attempt_number",
        "max_model_calls",
        "max_tool_calls",
        "max_depth",
    )
    @classmethod
    def ensure_positive_count(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("subagent limits must be positive")
        return value

    @field_validator("model_calls_used", "tool_calls_used", "source_count")
    @classmethod
    def ensure_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("subagent usage must not be negative")
        return value

    @field_validator("subagent_id", "status", "provenance")
    @classmethod
    def ensure_text_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("subagent lifecycle fields must not be blank")
        return stripped

    @field_validator("confidence")
    @classmethod
    def ensure_confidence_in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("subagent confidence must be between zero and one")
        return value


class MemoryCandidateExtractedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    memory_type: str
    status: str
    visibility: str
    text: str
    confidence: float
    source_event_start: int
    source_event_end: int
    repo_id: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None

    @field_validator(
        "memory_id",
        "memory_type",
        "status",
        "visibility",
        "text",
    )
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("confidence")
    @classmethod
    def ensure_confidence_in_range(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @field_validator("source_event_start", "source_event_end")
    @classmethod
    def ensure_non_negative_sequence(cls, value: int) -> int:
        if value < 0:
            raise ValueError("source event sequence must be non-negative")
        return value

    @field_validator("repo_id", "user_id", "tenant_id")
    @classmethod
    def ensure_optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank when provided")
        return stripped


class MemoryReviewRecordedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    memory_type: str
    previous_status: str
    status: str
    operator: str
    reason: str
    superseded_memory_ids: list[str] = []
    duplicate_of_memory_id: str | None = None

    @field_validator(
        "memory_id",
        "memory_type",
        "previous_status",
        "status",
        "operator",
        "reason",
    )
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("superseded_memory_ids")
    @classmethod
    def ensure_superseded_ids_are_non_blank(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            stripped = item.strip()
            if not stripped:
                raise ValueError("field must not be blank")
            normalized.append(stripped)
        return normalized

    @field_validator("duplicate_of_memory_id")
    @classmethod
    def ensure_duplicate_of_id_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank when provided")
        return stripped


class ClarificationRequestedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    clarification_id: str
    tool_call_id: str
    provider_call_id: str | None = None
    question: str = Field(max_length=MAX_CLARIFICATION_QUESTION_CHARS)
    choices: list[str] = Field(
        default_factory=list,
        max_length=MAX_CLARIFICATION_CHOICES,
    )
    context: str | None = Field(default=None, max_length=MAX_CLARIFICATION_CONTEXT_CHARS)
    assistant_message: str
    conversation: list[dict[str, Any]]
    model_calls_used: int
    tool_calls_executed: int
    # Optional MCP elicitation response schema + origin. None == agent.clarify and
    # is excluded from serialization so the existing flow stays byte-identical.
    response_schema: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    elicitation_source: str | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("attempt_number")
    @classmethod
    def ensure_positive_attempt(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("attempt_number must be positive")
        return value

    @field_validator("model_calls_used", "tool_calls_executed")
    @classmethod
    def ensure_non_negative_usage(cls, value: int) -> int:
        if value < 0:
            raise ValueError("clarification usage must not be negative")
        return value

    @field_validator(
        "clarification_id",
        "tool_call_id",
        "question",
        "assistant_message",
    )
    @classmethod
    def ensure_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("clarification fields must not be blank")
        return normalized

    @field_validator("choices")
    @classmethod
    def ensure_valid_choices(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > MAX_CLARIFICATION_CHOICE_CHARS for value in normalized):
            raise ValueError("clarification choices must be non-blank and bounded")
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("clarification choices must be unique")
        return normalized


class ClarificationRespondedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clarification_id: str
    content: str
    selected_choice: bool

    @field_validator("clarification_id", "content")
    @classmethod
    def ensure_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("clarification response fields must not be blank")
        return normalized


class ContextCapsuleCreatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capsule_id: str
    artifact_id: str
    schema_version: str
    source_hash: str
    source_event_range: ContextSourceEventRange
    previous_capsule_id: str | None = None

    @field_validator(
        "capsule_id",
        "artifact_id",
        "schema_version",
        "source_hash",
        "previous_capsule_id",
    )
    @classmethod
    def ensure_capsule_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("context capsule event fields must not be blank")
        return stripped


_EVENT_PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.SESSION_CREATED: SessionCreatedPayload,
    EventType.SESSION_TITLE_UPDATED: SessionTitleUpdatedPayload,
    EventType.USER_MESSAGE_RECEIVED: UserMessageReceivedPayload,
    EventType.TASK_PREPARED: TaskPreparedPayload,
    EventType.RUNTIME_PROVISIONED: RuntimeProvisionedPayload,
    EventType.HARNESS_ATTEMPT_STARTED: HarnessAttemptStartedPayload,
    EventType.ATTEMPT_OUTCOME_RECORDED: AttemptOutcomeRecordedPayload,
    EventType.ATTEMPT_CONTINUATION_STARTED: AttemptContinuationStartedPayload,
    EventType.MODEL_REQUEST_STARTED: ModelRequestStartedPayload,
    EventType.MODEL_RESPONSE_DELTA: ModelResponseDeltaPayload,
    EventType.MODEL_RESPONSE_RECEIVED: ModelResponseReceivedPayload,
    EventType.PLAN_UPDATED: PlanUpdatedPayload,
    EventType.SESSION_SUSPENDED: SessionSuspendedPayload,
    EventType.SESSION_RESUMED: SessionResumedPayload,
    EventType.CLARIFICATION_REQUESTED: ClarificationRequestedPayload,
    EventType.CLARIFICATION_RESPONDED: ClarificationRespondedPayload,
    EventType.TOOL_EXECUTION_COMPLETED: ToolExecutionCompletedPayload,
    EventType.CONTEXT_COMPACTED: ContextCompactedPayload,
    EventType.CONTEXT_CAPSULE_CREATED: ContextCapsuleCreatedPayload,
    EventType.CONTEXT_CONTINUATION_SELECTED: ContextContinuationSelectedPayload,
    EventType.SESSION_HANDOFF_COMMITTED: SessionHandoffCommittedPayload,
    EventType.SESSION_HANDOFF_RECEIVED: SessionHandoffReceivedPayload,
    EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED: (
        SessionHandoffWorkspaceDriftDetectedPayload
    ),
    EventType.SUBAGENT_STARTED: SubagentLifecyclePayload,
    EventType.SUBAGENT_COMPLETED: SubagentLifecyclePayload,
    EventType.SUBAGENT_FAILED: SubagentLifecyclePayload,
    EventType.SUBAGENT_CANCELLED: SubagentLifecyclePayload,
    EventType.MEMORY_CANDIDATE_EXTRACTED: MemoryCandidateExtractedPayload,
    EventType.MEMORY_REVIEW_RECORDED: MemoryReviewRecordedPayload,
}


class EventPayloadValidationError(ValueError):
    """Raised when an event payload does not satisfy its contract."""


def event_payload_schema_for(event_type: EventType) -> dict[str, Any]:
    payload_model = _EVENT_PAYLOAD_MODELS.get(event_type)
    if payload_model is None:
        raise KeyError(f"no payload schema registered for {event_type.value}")
    schema = payload_model.model_json_schema()
    if not isinstance(schema, dict):
        raise TypeError("event payload schema must be a dictionary")
    return schema


def validate_event_payload(
    event_type: EventType,
    payload: dict[str, Any],
) -> dict[str, Any]:
    payload_model = _EVENT_PAYLOAD_MODELS.get(event_type)
    if payload_model is None:
        raise KeyError(f"no payload schema registered for {event_type.value}")
    try:
        validated = payload_model.model_validate(payload)
    except ValidationError as exc:
        raise EventPayloadValidationError(
            f"invalid payload for {event_type.value}",
        ) from exc
    return validated.model_dump()
