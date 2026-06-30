from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class ArtifactRetentionProfile(StrEnum):
    SHORT_LIVED = "short_lived"
    STANDARD = "standard"
    EXTENDED = "extended"


class ArtifactRetentionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: ArtifactRetentionProfile
    ttl: timedelta

    @field_validator("ttl")
    @classmethod
    def ensure_positive_ttl(cls, value: timedelta) -> timedelta:
        if value <= timedelta(0):
            raise ValueError("artifact retention ttl must be positive")
        return value

    def retained_until_for(self, created_at: datetime) -> datetime:
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return created_at.astimezone(UTC) + self.ttl
