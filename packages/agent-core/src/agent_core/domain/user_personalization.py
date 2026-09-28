from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_USER_INSTRUCTIONS_CHARACTERS = 12_000


def normalize_user_instructions(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("user instructions must not be blank")
    if "\x00" in normalized:
        raise ValueError("user instructions must not contain NUL characters")
    if len(normalized) > MAX_USER_INSTRUCTIONS_CHARACTERS:
        raise ValueError(
            f"user instructions must not exceed {MAX_USER_INSTRUCTIONS_CHARACTERS} characters"
        )
    return normalized


class UserPersonalization(BaseModel):
    """Current user-authored standing instructions for future Agent turns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(max_length=255)
    instructions: str | None = None
    revision: int = Field(ge=1)
    updated_at: datetime
    operator: str = Field(max_length=255)

    @field_validator("user_id", "operator")
    @classmethod
    def require_canonical_identity(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("identity fields must be non-blank and trimmed")
        return value

    @field_validator("instructions")
    @classmethod
    def normalize_instructions(cls, value: str | None) -> str | None:
        return None if value is None else normalize_user_instructions(value)

    @model_validator(mode="after")
    def require_timezone(self) -> UserPersonalization:
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        return self
