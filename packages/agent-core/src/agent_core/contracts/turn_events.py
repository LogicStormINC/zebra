"""Payload contracts for Turn lifecycle events (ADR-026)."""

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

_LEGACY_TURN_ID_PATTERN = re.compile(r"legacy-turn:\d+\Z")


def validate_turn_identity(value: str) -> str:
    """Turn ids are UUIDs, or the explicit legacy replay format."""

    try:
        UUID(value)
        return value
    except ValueError:
        pass
    if _LEGACY_TURN_ID_PATTERN.fullmatch(value):
        return value
    raise ValueError("turn_id must be a UUID or legacy-turn:<sequence>")


def _require_turn_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("turn fields must not be blank")
    return value


class TurnCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    turn_index: StrictInt = Field(ge=0)
    summary: str = ""
    closes_segment: StrictBool = False
    attempt_number: StrictInt = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("turn_id")
    @classmethod
    def require_turn_id(cls, value: str) -> str:
        return validate_turn_identity(_require_turn_text(value))


class TurnFailedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    turn_index: StrictInt = Field(ge=0)
    reason: str = ""
    closes_segment: StrictBool = Field(default=True)
    attempt_number: StrictInt = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("turn_id")
    @classmethod
    def require_turn_id(cls, value: str) -> str:
        return validate_turn_identity(_require_turn_text(value))


class TurnCancelledPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    turn_index: StrictInt = Field(ge=0)
    reason: str = ""

    @field_validator("turn_id")
    @classmethod
    def require_turn_id(cls, value: str) -> str:
        return validate_turn_identity(_require_turn_text(value))
