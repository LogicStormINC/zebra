from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import SessionId


class ToolRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    sequence: int = Field(ge=0)
    tool_name: str
    status: str
    idempotency_key: str | None = None
    output: str = ""
    artifact_uri: str | None = None
    created_at: datetime

    @field_validator("tool_name", "status")
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("tool run fields must not be blank")
        return stripped

    @field_validator("artifact_uri")
    @classmethod
    def ensure_artifact_uri_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("artifact_uri must not be blank when set")
        return stripped

    @field_validator("created_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value
