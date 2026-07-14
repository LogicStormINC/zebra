from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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

    @model_validator(mode="after")
    def validate_tool_message_shape(self) -> "SessionMessage":
        if self.role is MessageRole.TOOL and self.tool_call_id is None:
            raise ValueError("tool messages require tool_call_id")
        if self.role is not MessageRole.TOOL and self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid for tool messages")
        if self.tool_calls and self.role is not MessageRole.ASSISTANT:
            raise ValueError("tool_calls are only valid for assistant messages")
        return self
