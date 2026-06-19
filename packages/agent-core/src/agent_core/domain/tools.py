from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import ToolCallId


class ToolCallStatus(StrEnum):
    PROPOSED = "proposed"
    EXECUTED = "executed"
    FAILED = "failed"


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_call_id: ToolCallId
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("name")
    @classmethod
    def ensure_name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("created_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_call_id: ToolCallId
    status: ToolCallStatus
    output: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
