"""Transient-only Port. Implementations enforce trusted authority and fencing."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.leases import LeaseFence
from agent_core.domain.stream_admission import TransientCapacityPolicy
from agent_core.domain.transient_output import TransientGeneration, TransientTextFrame
from agent_core.ports.live_event_fanout import LiveEventCursor, _require_namespace

MAX_TRANSIENT_AUTHORIZATION_SECONDS = 30


class TransientStreamScope(BaseModel):
    """Internal binding resolved by trusted composition, never accepted from wire."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: str
    authority_scope: OpaqueAuthorityScope
    generation: TransientGeneration

    @field_validator("deployment_namespace")
    @classmethod
    def require_namespace(cls, value: str) -> str:
        return _require_namespace(value)

    @model_validator(mode="after")
    def require_session_scope(self) -> TransientStreamScope:
        if not self.authority_scope.allows_session(self.generation.segment_id):
            raise ValueError("generation segment is outside authority scope")
        return self


class TransientWriterAuthorization(BaseModel):
    """Server-issued process-local gate handle; constructing this grants nothing.

    Adapter activation MUST resolve gate_context_ref against the verified gate
    for this exact call/scope/full LeaseFence, and fresh durable lease/Grant authority.
    This handle adds no durable gate row and no per-frame SQL lookup.
    It must not trust an incoming frame or a caller's publication boolean.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: TransientStreamScope
    lease_fence: LeaseFence
    gate_context_ref: str = Field(min_length=1, max_length=128)
    capacity_policy: TransientCapacityPolicy | None = None
    capacity_digest: str | None = Field(default=None, min_length=64, max_length=64)
    category: Literal["ordinary_public_text"] = "ordinary_public_text"
    issued_at: datetime
    expires_at: datetime
    lease_expires_at: datetime
    grant_expires_at: datetime

    @field_validator("issued_at", "expires_at", "lease_expires_at", "grant_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("transient authority timestamps must be timezone-aware")
        return value

    @field_validator("gate_context_ref")
    @classmethod
    def require_gate_reference(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("gate decision reference must be trimmed and contain no controls")
        return value

    @model_validator(mode="after")
    def require_bounded_window(self) -> TransientWriterAuthorization:
        if (self.capacity_policy is None) != (self.capacity_digest is None):
            raise ValueError("capacity policy and digest must appear together")
        if self.capacity_policy is not None and self.capacity_digest != self.capacity_policy.digest:
            raise ValueError("capacity policy digest mismatch")
        if self.lease_fence.fencing_token != self.scope.generation.lease_fence:
            raise ValueError("full lease fence token must match generation")
        ceiling = min(
            self.issued_at + timedelta(seconds=MAX_TRANSIENT_AUTHORIZATION_SECONDS),
            self.lease_expires_at,
            self.grant_expires_at,
        )
        if not self.issued_at < self.expires_at <= ceiling:
            raise ValueError("transient authority must fit lease/Grant and 30-second ceiling")
        return self

    def ensure_frame(
        self, frame: TransientTextFrame, *, now: datetime, current_fence: LeaseFence
    ) -> None:
        """Necessary local checks; adapter still checks current fence atomically."""
        if now.utcoffset() is None or not self.issued_at <= now < self.expires_at:
            raise ValueError("transient writer authority is not current")
        if current_fence != self.lease_fence:
            raise ValueError("transient writer full lease fence is stale")
        if frame.generation != self.scope.generation:
            raise ValueError("frame generation does not match writer authority")


class TransientResumeCursor(BaseModel):
    """Internal decoded cursor; API must authenticate its opaque wire token.

    Scope comparison is necessary but not a substitute for fresh read authority.
    durable_sequence/frame_index never advance from a live offset or Redis ID.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    version: Literal[2] = 2
    scope: TransientStreamScope
    durable_sequence: int = Field(strict=True, ge=0)
    durable_frame_index: int = Field(default=0, strict=True, ge=0)
    live_cursor: LiveEventCursor | None = None
    live_offset: int | None = Field(default=None, strict=True, ge=0)

    @field_validator("version", mode="before")
    @classmethod
    def require_integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("version must be an integer")
        return value

    @model_validator(mode="after")
    def require_live_pair(self) -> TransientResumeCursor:
        if self.live_offset is not None and self.live_cursor is None:
            raise ValueError("live offset requires a live cursor")
        return self

    def ensure_scope(self, scope: TransientStreamScope) -> None:
        if self.scope != scope:
            raise ValueError("resume cursor belongs to another stream scope")


class TransientOutputBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    frames: tuple[TransientTextFrame, ...] = Field(default=(), max_length=100)
    next_cursor: TransientResumeCursor
    resync_required: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def require_bounded_scoped_frames(self) -> TransientOutputBatch:
        if self.resync_required and self.frames:
            raise ValueError("resync cannot carry provisional frames")
        if sum(len(frame.wire_bytes()) for frame in self.frames) > 256 * 1024:
            raise ValueError("transient batch exceeds 256KiB UTF-8 budget")
        if any(frame.generation != self.next_cursor.scope.generation for frame in self.frames):
            raise ValueError("batch frames must match cursor generation")
        return self


class TransientOutputPort(Protocol):
    """Bounded adapters, not execution authority or a token-signing framework.

    activate validates server-issued gate evidence and fresh durable authority;
    publish atomically checks active generation/full LeaseFence, expiry, contiguous offset
    and capacity with append. Equal offset/content dedupes; mismatch rejects.
    invalidate is idempotent and permanently fences that generation. A lower or
    reused revoked fence cannot activate again. Reads reauthorize scope/deadline,
    never extend retention; gaps/lost Redis return resync, not execution failure.
    """

    def activate(self, authorization: TransientWriterAuthorization) -> None: ...

    def publish(
        self, authorization: TransientWriterAuthorization, frame: TransientTextFrame
    ) -> LiveEventCursor: ...

    def invalidate(self, scope: TransientStreamScope) -> None: ...

    def capture_barrier(self, scope: TransientStreamScope) -> TransientResumeCursor: ...

    def read_after(
        self,
        *,
        scope: TransientStreamScope,
        cursor: TransientResumeCursor,
        authorized_until: datetime,
        count: int = 100,
        block_ms: int = 0,
    ) -> TransientOutputBatch: ...
