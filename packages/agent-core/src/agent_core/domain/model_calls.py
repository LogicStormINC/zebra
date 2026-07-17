from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import SessionId


class ModelCallRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    sequence: int = Field(ge=0)
    provider: str | None = None
    model_name: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    input_token_limit: int | None = Field(default=None, ge=0)
    input_token_estimate_error: int | None = None
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    cache_hit: bool | None = None
    cost_usd: float | None = Field(default=None, ge=0)
    assistant_message: str = ""
    tool_call_count: int = Field(ge=0)
    created_at: datetime

    @field_validator("provider", "model_name")
    @classmethod
    def ensure_optional_fields_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("model call fields must not be blank when set")
        return stripped

    @field_validator("assistant_message")
    @classmethod
    def ensure_assistant_message_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("assistant_message must not be blank")
        return stripped

    @field_validator("created_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value
