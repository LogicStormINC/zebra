from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PendingToolState(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ContextCapsule(BaseModel):
    model_config = ConfigDict(frozen=True)

    capsule_id: str
    version: str = "1.0"
    objective: str
    constraints: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    plan: tuple[str, ...] = ()
    touched_files: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    pending_tools: tuple[PendingToolState, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    immediate_next: str
    source_hash: str
    profile: str = "zebra-deterministic-v1"
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime

    @field_validator(
        "capsule_id",
        "version",
        "objective",
        "immediate_next",
        "source_hash",
        "profile",
    )
    @classmethod
    def ensure_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("context capsule fields must not be blank")
        return stripped

    @field_validator("created_at")
    @classmethod
    def ensure_created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("context capsule created_at must be timezone-aware")
        return value
