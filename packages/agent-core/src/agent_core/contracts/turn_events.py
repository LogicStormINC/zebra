"""Payload contracts for Turn lifecycle events (ADR-026)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_turn_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("turn fields must not be blank")
    return value


class TurnCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    turn_index: int = Field(ge=0)
    summary: str = ""
    closes_segment: bool = False
    attempt_number: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("turn_id")
    @classmethod
    def require_turn_id(cls, value: str) -> str:
        return _require_turn_text(value)


class TurnFailedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    turn_index: int = Field(ge=0)
    reason: str = ""
    closes_segment: bool = Field(default=True)
    attempt_number: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("turn_id")
    @classmethod
    def require_turn_id(cls, value: str) -> str:
        return _require_turn_text(value)


class TurnCancelledPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    turn_index: int = Field(ge=0)
    reason: str = ""

    @field_validator("turn_id")
    @classmethod
    def require_turn_id(cls, value: str) -> str:
        return _require_turn_text(value)
