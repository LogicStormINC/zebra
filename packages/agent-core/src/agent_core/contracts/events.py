from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from agent_core.domain.events import EventType


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


class UserMessageReceivedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str

    @field_validator("content")
    @classmethod
    def ensure_content_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


class TaskPreparedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    user_input: str
    workspace_root: str | None = None
    policy_profile: str | None = None
    max_attempts: int | None = None
    max_model_calls: int | None = None
    max_tool_calls: int | None = None

    @field_validator("title", "user_input")
    @classmethod
    def ensure_required_text_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("workspace_root", "policy_profile")
    @classmethod
    def ensure_optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank when provided")
        return stripped

    @field_validator("max_attempts", "max_model_calls", "max_tool_calls")
    @classmethod
    def ensure_optional_positive_int(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("field must be positive when provided")
        return value


class ToolExecutionCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    tool_name: str
    status: str
    output: str
    metadata: dict[str, object]

    @field_validator("attempt_number")
    @classmethod
    def ensure_positive_attempt_number(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("attempt_number must be positive")
        return value

    @field_validator("tool_name", "status")
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped


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


class SessionSuspendedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_name: str
    snapshot_id: str
    snapshot_path: str

    @field_validator("runtime_name", "snapshot_id", "snapshot_path")
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped


class SessionResumedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_name: str
    snapshot_id: str
    workspace_root: str

    @field_validator("runtime_name", "snapshot_id", "workspace_root")
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped


_EVENT_PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.SESSION_CREATED: SessionCreatedPayload,
    EventType.USER_MESSAGE_RECEIVED: UserMessageReceivedPayload,
    EventType.TASK_PREPARED: TaskPreparedPayload,
    EventType.SESSION_SUSPENDED: SessionSuspendedPayload,
    EventType.SESSION_RESUMED: SessionResumedPayload,
    EventType.TOOL_EXECUTION_COMPLETED: ToolExecutionCompletedPayload,
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
