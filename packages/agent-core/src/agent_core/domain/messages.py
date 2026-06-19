from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from agent_core.domain.identifiers import MessageId


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
