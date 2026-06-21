from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.identifiers import SessionId


class WorkerLease(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    worker_id: str
    checkpoint: int = Field(default=0, ge=0)
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime

    @field_validator("worker_id")
    @classmethod
    def ensure_worker_id_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("worker_id must not be blank")
        return stripped

    @field_validator("acquired_at", "heartbeat_at", "expires_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("lease timestamps must be timezone-aware")
        return value
