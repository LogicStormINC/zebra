from datetime import datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import SessionId

DEFAULT_MAX_LEASE_TTL = timedelta(hours=1)


class LeaseConflictError(ValueError):
    """Raised when an active lease prevents a new acquisition."""


class LeaseLostError(RuntimeError):
    """Raised when a fenced lease mutation no longer owns the session."""


class LeaseCheckpointRegressionError(ValueError):
    """Raised when a lease mutation would move its recovery checkpoint backwards."""


class LeaseFence(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_plane_epoch: UUID
    fencing_token: int = Field(ge=1)
    owner_instance_id: str

    @field_validator("owner_instance_id")
    @classmethod
    def ensure_owner_instance_id_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("owner_instance_id must not be blank")
        return stripped


class WorkerLease(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    fence: LeaseFence
    checkpoint: int = Field(default=0, ge=0)
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime

    @field_validator("acquired_at", "heartbeat_at", "expires_at")
    @classmethod
    def ensure_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("lease timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ensure_timestamp_order(self) -> Self:
        if not self.acquired_at <= self.heartbeat_at < self.expires_at:
            raise ValueError(
                "lease timestamps must satisfy acquired_at <= heartbeat_at < expires_at"
            )
        return self

    @property
    def owner_instance_id(self) -> str:
        return self.fence.owner_instance_id

    @property
    def worker_id(self) -> str:
        """Compatibility view for callers that only display the logical owner."""

        return self.owner_instance_id
