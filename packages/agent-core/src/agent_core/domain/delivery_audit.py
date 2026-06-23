from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import SessionId


class DeliveryAuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    action: str
    status: str
    status_code: int = Field(ge=100, le=599)
    policy_profile: str | None = None
    idempotency_key: str | None = None
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("action", "status")
    @classmethod
    def ensure_required_fields_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("delivery audit fields must not be blank")
        return stripped

    @field_validator("policy_profile", "idempotency_key")
    @classmethod
    def ensure_optional_fields_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("delivery audit optional fields must not be blank when set")
        return stripped

    @field_validator("created_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value
