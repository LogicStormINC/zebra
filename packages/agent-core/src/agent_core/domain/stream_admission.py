"""Run-pinned stream negotiation, additive to existing execution admission."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
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


class TransientCapacityPolicy(BaseModel):
    """Server-owned retained accounting limits, distinct from client intent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    epoch: str = Field(default="capacity-v1", min_length=1, max_length=128)
    generation_bytes: int = Field(default=8 * 1024 * 1024, strict=True, gt=0, le=2**53 - 1)
    generation_rows: int = Field(default=8192, strict=True, gt=0, le=2**53 - 1)
    run_bytes: int = Field(default=32 * 1024 * 1024, strict=True, gt=0, le=2**53 - 1)
    run_rows: int = Field(default=32768, strict=True, gt=0, le=2**53 - 1)
    run_slots: int = Field(default=32, strict=True, gt=0, le=256)
    tenant_bytes: int = Field(default=128 * 1024 * 1024, strict=True, gt=0, le=2**53 - 1)
    tenant_rows: int = Field(default=131072, strict=True, gt=0, le=2**53 - 1)
    tenant_slots: int = Field(default=128, strict=True, gt=0, le=512)
    deployment_bytes: int = Field(default=512 * 1024 * 1024, strict=True, gt=0, le=2**53 - 1)
    deployment_rows: int = Field(default=524288, strict=True, gt=0, le=2**53 - 1)
    deployment_slots: int = Field(default=512, strict=True, gt=0, le=512)
    metadata_bytes: int = Field(default=65536, strict=True, ge=16384, le=65536)
    offset_bytes: int = Field(default=512, strict=True, ge=256, le=512)
    active_seconds: int = Field(default=3600, strict=True, gt=0, le=3600)
    ended_seconds: int = Field(default=600, strict=True, gt=0, le=600)

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("capacity version must be integer")
        return value

    @field_validator("epoch")
    @classmethod
    def bounded_epoch(cls, value: str) -> str:
        if value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("capacity epoch must be trimmed without controls")
        return value

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()


class RunStreamAdmission(BaseModel):
    """Persist once with Run admission; a reconnect cannot renegotiate it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: TaskId
    run_id: str = Field(min_length=1, max_length=128)
    mode: StreamMode = StreamMode.LEGACY
    capabilities: StreamCapabilities = Field(default_factory=StreamCapabilities)
    capacity_policy: TransientCapacityPolicy | None = None
    capacity_digest: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("run_id")
    @classmethod
    def require_trimmed_run(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("run_id must be trimmed and contain no controls")
        return value

    @model_validator(mode="after")
    def require_compatible_client(self) -> RunStreamAdmission:
        if (self.capacity_policy is None) != (self.capacity_digest is None):
            raise ValueError("capacity policy and digest must appear together")
        if self.capacity_policy is not None and self.capacity_digest != self.capacity_policy.digest:
            raise ValueError("capacity policy digest mismatch")
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
