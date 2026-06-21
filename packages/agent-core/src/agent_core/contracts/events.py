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


_EVENT_PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.SESSION_CREATED: SessionCreatedPayload,
    EventType.USER_MESSAGE_RECEIVED: UserMessageReceivedPayload,
    EventType.TOOL_EXECUTION_COMPLETED: ToolExecutionCompletedPayload,
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
