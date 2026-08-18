from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId

_MAX_NAMESPACE_LENGTH = 255
_MAX_CURSOR_LENGTH = 128


def _require_namespace(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("deployment_namespace must be non-blank and trimmed")
    if len(value) > _MAX_NAMESPACE_LENGTH:
        raise ValueError("deployment_namespace exceeds 255 characters")
    return value


@dataclass(frozen=True, slots=True)
class LiveEventCursor:
    """Opaque provider cursor used after a replay barrier."""

    value: str
    stream_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value or self.value != self.value.strip():
            raise ValueError("live event cursor must be non-blank and trimmed")
        if len(self.value) > _MAX_CURSOR_LENGTH:
            raise ValueError("live event cursor exceeds 128 characters")
        if self.stream_ref is not None and (
            not isinstance(self.stream_ref, str)
            or not self.stream_ref
            or self.stream_ref != self.stream_ref.strip()
        ):
            raise ValueError("live event cursor stream_ref must be non-blank and trimmed")


@dataclass(frozen=True, slots=True)
class LiveEventEnvelope:
    """A transient copy of a canonical Event for live delivery."""

    deployment_namespace: str
    event: SessionEvent
    cursor: LiveEventCursor

    def __post_init__(self) -> None:
        _require_namespace(self.deployment_namespace)


@dataclass(frozen=True, slots=True)
class LiveEventBatch:
    """A bounded tail read and the cursor after every inspected entry."""

    events: tuple[LiveEventEnvelope, ...]
    next_cursor: LiveEventCursor


class LiveEventFanoutPort(Protocol):
    """Ephemeral live tail; durable Event replay remains the authority."""

    def capture_barrier(
        self,
        *,
        deployment_namespace: str,
        session_id: SessionId,
    ) -> LiveEventCursor: ...

    def publish(
        self,
        *,
        deployment_namespace: str,
        event: SessionEvent,
    ) -> LiveEventCursor: ...

    def read_after(
        self,
        *,
        deployment_namespace: str,
        session_id: SessionId,
        barrier: LiveEventCursor,
        durable_sequence: int,
        count: int = 100,
        block_ms: int = 0,
    ) -> LiveEventBatch: ...
