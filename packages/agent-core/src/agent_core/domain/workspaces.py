from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from agent_core.domain.identifiers import SessionId


class WorkspaceStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkspaceProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    workspace_root: str
    prepared_at: datetime
    updated_at: datetime
    current_sequence: int
    status: WorkspaceStatus
    policy_profile: str | None = None
    last_attempt_number: int | None = None
    runtime_name: str | None = None
    snapshot_id: str | None = None
    snapshot_path: str | None = None

    @field_validator("workspace_root")
    @classmethod
    def ensure_workspace_root_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("workspace_root must not be blank")
        return stripped

    @field_validator("policy_profile", "runtime_name", "snapshot_id", "snapshot_path")
    @classmethod
    def ensure_optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("optional text field must not be blank when provided")
        return stripped
