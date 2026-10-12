"""Run-pinned stream negotiation, additive to existing execution admission."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import TaskId


class StreamMode(StrEnum):
    LEGACY = "legacy"
    TRANSIENT_V2 = "transient_v2"


class StreamCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    wire_version: Literal[1, 2] = 1
    provisional_draft_label: bool = Field(default=False, strict=True)
    replace_message: bool = Field(default=False, strict=True)
    reset_provisional: bool = Field(default=False, strict=True)
    scoped_resume: bool = Field(default=False, strict=True)

    @field_validator("wire_version", mode="before")
    @classmethod
    def require_integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("wire_version must be an integer")
        return value

    @property
    def supports_v2(self) -> bool:
        return (
            self.wire_version == 2
            and self.provisional_draft_label
            and self.replace_message
            and self.reset_provisional
            and self.scoped_resume
        )


class RunStreamAdmission(BaseModel):
    """Persist once with Run admission; a reconnect cannot renegotiate it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: TaskId
    run_id: str = Field(min_length=1, max_length=128)
    mode: StreamMode = StreamMode.LEGACY
    capabilities: StreamCapabilities = Field(default_factory=StreamCapabilities)

    @field_validator("run_id")
    @classmethod
    def require_trimmed_run(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("run_id must be trimmed and contain no controls")
        return value

    @model_validator(mode="after")
    def require_compatible_client(self) -> RunStreamAdmission:
        if self.mode is StreamMode.TRANSIENT_V2 and not self.capabilities.supports_v2:
            raise ValueError("transient v2 requires draft label, replace, reset and scoped resume")
        return self

    def ensure_observer_compatible(self, capabilities: StreamCapabilities) -> None:
        if self.mode is StreamMode.TRANSIENT_V2 and not capabilities.supports_v2:
            raise ValueError("observer cannot resume this v2 Run; upgrade or use durable snapshot")


def negotiate_stream_mode(
    *, capabilities: StreamCapabilities, transient_enabled: bool = False
) -> StreamMode:
    """Server admission choice only; local/missing/config-disabled stays legacy."""
    return (
        StreamMode.TRANSIENT_V2
        if transient_enabled and capabilities.supports_v2
        else StreamMode.LEGACY
    )
