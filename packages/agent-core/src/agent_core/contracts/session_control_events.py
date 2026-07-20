from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionSuspendedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_name: str | None = None
    snapshot_id: str | None = None
    snapshot_path: str | None = None
    reason: str | None = None
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

    runtime_name: str
    snapshot_id: str
    workspace_root: str

    @field_validator("runtime_name", "snapshot_id", "workspace_root")
    @classmethod
    def ensure_field_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped
