from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import MessageId
from agent_core.domain.tools import ToolCall


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class SessionMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: MessageId
    role: MessageRole
    content: str
    created_at: datetime
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    provider_reasoning_content: str | None = Field(default=None, exclude=True, repr=False)

    @field_validator("content")
    @classmethod
    def ensure_content_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped

    @field_validator("created_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @field_validator("tool_call_id")
    @classmethod
    def ensure_tool_call_id_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("tool_call_id must not be blank when set")
        return stripped

    @field_validator("provider_reasoning_content")
    @classmethod
    def ensure_provider_reasoning_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("provider_reasoning_content must not be blank when set")
        return value

    @model_validator(mode="after")
    def validate_tool_message_shape(self) -> "SessionMessage":
        if self.role is MessageRole.TOOL and self.tool_call_id is None:
            raise ValueError("tool messages require tool_call_id")
        if self.role is not MessageRole.TOOL and self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid for tool messages")
        if self.tool_calls and self.role is not MessageRole.ASSISTANT:
            raise ValueError("tool_calls are only valid for assistant messages")
        if self.provider_reasoning_content is not None and (
            self.role is not MessageRole.ASSISTANT or not self.tool_calls
        ):
            raise ValueError(
                "provider_reasoning_content is only valid for assistant tool-call messages"
            )
        return self


def without_superseded_operation_failures(
    messages: tuple[SessionMessage, ...],
) -> tuple[SessionMessage, ...]:
    succeeded: set[str] = set()
    superseded: set[str] = set()
    for message in reversed(messages):
        if message.role is not MessageRole.TOOL:
            continue
        operation_key = message.metadata.get("operation_key")
        status = message.metadata.get("tool_result_status")
        if not isinstance(operation_key, str) or not operation_key:
            continue
        if status == "succeeded":
            succeeded.add(operation_key)
        elif status == "failed" and operation_key in succeeded and message.tool_call_id:
            superseded.add(message.tool_call_id)
    if not superseded:
        return messages
    active: list[SessionMessage] = []
    for message in messages:
        if message.role is MessageRole.TOOL and message.tool_call_id in superseded:
            continue
        if message.role is MessageRole.ASSISTANT and message.tool_calls:
            calls = tuple(
                call
                for call in message.tool_calls
                if (call.provider_call_id or str(call.tool_call_id)) not in superseded
            )
            if not calls:
                continue
            if calls != message.tool_calls:
                message = message.model_copy(update={"tool_calls": calls})
        active.append(message)
    return tuple(active)
