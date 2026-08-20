from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionSuspendedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_name: str | None = None
    snapshot_id: str | None = None
    snapshot_path: str | None = None
    reason: str | None = None
    child_task_ids: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime_name", "snapshot_id", "snapshot_path", "reason")
    @classmethod
    def ensure_field_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("child_task_ids")
    @classmethod
    def ensure_child_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("child_task_ids must not be empty when present")
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("child_task_ids entries must not be blank")
        return normalized

    @model_validator(mode="after")
    def ensure_snapshot_or_reason(self) -> "SessionSuspendedPayload":
        snapshot = (self.runtime_name, self.snapshot_id, self.snapshot_path)
        if any(snapshot) and not all(snapshot):
            raise ValueError("runtime suspension requires a complete snapshot")
        if not all(snapshot) and self.reason is None:
            raise ValueError("suspension requires a runtime snapshot or reason")
        return self


class SessionResumedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_name: str | None = None
    snapshot_id: str | None = None
    workspace_root: str | None = None
    reason: str | None = None

    @field_validator("runtime_name", "snapshot_id", "workspace_root", "reason")
    @classmethod
    def ensure_field_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @model_validator(mode="after")
    def ensure_complete_snapshot(self) -> "SessionResumedPayload":
        snapshot = (self.runtime_name, self.snapshot_id, self.workspace_root)
        if any(snapshot) and not all(snapshot):
            raise ValueError("snapshot resume requires runtime, snapshot and workspace")
        return self
