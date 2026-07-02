from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.identifiers import MemoryId, SessionId


class MemoryType(StrEnum):
    PREFERENCE = "preference"
    PROJECT_RULE = "project_rule"
    PROCEDURE = "procedure"
    EPISODIC = "episodic"
    FAILED_ATTEMPT = "failed_attempt"
    ARCHITECTURE_FACT = "architecture_fact"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DELETED = "deleted"


class MemoryVisibility(StrEnum):
    USER = "user"
    REPO = "repo"
    TENANT = "tenant"


class MemoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_id: MemoryId
    memory_type: MemoryType
    text: str
    confidence: float = Field(ge=0, le=1)
    status: MemoryStatus = MemoryStatus.CANDIDATE
    visibility: MemoryVisibility
    tenant_id: str | None = None
    user_id: str | None = None
    repo_id: str | None = None
    source_session_id: SessionId | None = None
    source_event_start: int | None = Field(default=None, ge=0)
    source_event_end: int | None = Field(default=None, ge=0)
    source_commit_sha: str | None = None
    superseded_by: MemoryId | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_record(self) -> "MemoryRecord":
        text = self.text.strip()
        if not text:
            raise ValueError("memory text must not be blank")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "tenant_id", _normalize_optional_text(self.tenant_id))
        object.__setattr__(self, "user_id", _normalize_optional_text(self.user_id))
        object.__setattr__(self, "repo_id", _normalize_optional_text(self.repo_id))
        object.__setattr__(
            self,
            "source_commit_sha",
            _normalize_optional_text(self.source_commit_sha),
        )
        _ensure_timezone_aware(self.created_at, field_name="created_at")
        _ensure_timezone_aware(self.updated_at, field_name="updated_at")
        if self.expires_at is not None:
            _ensure_timezone_aware(self.expires_at, field_name="expires_at")
        if (self.source_event_start is None) != (self.source_event_end is None):
            raise ValueError("source event range must include both start and end")
        if (
            self.source_event_start is not None
            and self.source_event_end is not None
            and self.source_event_end < self.source_event_start
        ):
            raise ValueError("source event range must be ordered")
        if self.visibility is MemoryVisibility.REPO and self.repo_id is None:
            raise ValueError("repo visibility requires repo_id")
        if self.visibility is MemoryVisibility.USER and self.user_id is None:
            raise ValueError("user visibility requires user_id")
        if self.visibility is MemoryVisibility.TENANT and self.tenant_id is None:
            raise ValueError("tenant visibility requires tenant_id")
        if self.status is MemoryStatus.SUPERSEDED and self.superseded_by is None:
            raise ValueError("superseded memory requires superseded_by")
        if self.superseded_by is not None and self.status is not MemoryStatus.SUPERSEDED:
            raise ValueError("superseded_by can only be set for superseded memory")
        return self


class MemoryQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str | None = None
    user_id: str | None = None
    repo_id: str | None = None
    memory_types: tuple[MemoryType, ...] = ()
    statuses: tuple[MemoryStatus, ...] = (MemoryStatus.CONFIRMED,)
    visibility: MemoryVisibility | None = None
    limit: int = Field(default=50, ge=1, le=500)

    @model_validator(mode="after")
    def validate_query(self) -> "MemoryQuery":
        object.__setattr__(self, "tenant_id", _normalize_optional_text(self.tenant_id))
        object.__setattr__(self, "user_id", _normalize_optional_text(self.user_id))
        object.__setattr__(self, "repo_id", _normalize_optional_text(self.repo_id))
        if self.tenant_id is None and self.user_id is None and self.repo_id is None:
            raise ValueError("memory query requires at least one scope")
        if self.visibility is MemoryVisibility.REPO and self.repo_id is None:
            raise ValueError("repo visibility query requires repo_id")
        if self.visibility is MemoryVisibility.USER and self.user_id is None:
            raise ValueError("user visibility query requires user_id")
        if self.visibility is MemoryVisibility.TENANT and self.tenant_id is None:
            raise ValueError("tenant visibility query requires tenant_id")
        return self


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _ensure_timezone_aware(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
