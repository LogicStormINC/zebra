"""Stable AG-UI identity, cursor and resume value objects."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

from ag_ui.core import Event
from agent_core.domain.identifiers import SessionId
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_PROJECTION_ID_CHARS = 256
MAX_CURSOR_CHARS = 2_048
MAX_RESUME_ENTRIES = 64


class AgUiProjectionError(ValueError):
    """Raised when durable facts cannot be projected safely."""


def _required_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} exceeds its maximum length")
    return normalized


class AgUiRunIdentity(BaseModel):
    """The externally stable Task/thread and Segment/run binding."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    session_id: SessionId
    thread_id: str = Field(max_length=MAX_PROJECTION_ID_CHARS)
    run_id: str = Field(max_length=MAX_PROJECTION_ID_CHARS)
    parent_run_id: str | None = Field(default=None, max_length=MAX_PROJECTION_ID_CHARS)

    @field_validator("thread_id", "run_id", "parent_run_id")
    @classmethod
    def normalize_identity_text(cls, value: str | None) -> str | None:
        return None if value is None else _required_text(value, "identity", MAX_PROJECTION_ID_CHARS)


class AgUiCursor(BaseModel):
    """Opaque reconnect position bound to one exact durable Event."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    version: int = Field(default=1, ge=1, le=1)
    thread_id: str = Field(max_length=MAX_PROJECTION_ID_CHARS)
    run_id: str = Field(max_length=MAX_PROJECTION_ID_CHARS)
    sequence: int = Field(ge=0)
    event_id: str = Field(max_length=MAX_PROJECTION_ID_CHARS)

    @field_validator("thread_id", "run_id", "event_id")
    @classmethod
    def normalize_cursor_text(cls, value: str) -> str:
        return _required_text(value, "cursor value", MAX_PROJECTION_ID_CHARS)

    def encode(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).decode()
        return encoded.rstrip("=")

    @classmethod
    def decode(cls, token: str) -> Self:
        if not isinstance(token, str) or not token or len(token) > MAX_CURSOR_CHARS:
            raise AgUiProjectionError("cursor token is malformed")
        try:
            padding = "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(token + padding)
            payload = json.loads(raw)
            return cls.model_validate(payload)
        except (
            ValueError,
            TypeError,
            binascii.Error,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise AgUiProjectionError("cursor token is malformed") from exc


class AgUiResumeEntry(BaseModel):
    """One deterministic durable-interrupt response for a resume request."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    interrupt_id: str = Field(
        validation_alias="interruptId",
        serialization_alias="interruptId",
        max_length=MAX_PROJECTION_ID_CHARS,
    )
    status: str = Field(max_length=32)
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("interrupt_id", "status")
    @classmethod
    def normalize_resume_text(cls, value: str) -> str:
        return _required_text(value, "resume field", MAX_PROJECTION_ID_CHARS)


class AgUiResumeRequest(BaseModel):
    """Provider-neutral resume identity; validation against durable state is later."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    thread_id: str = Field(
        validation_alias="threadId",
        serialization_alias="threadId",
        max_length=MAX_PROJECTION_ID_CHARS,
    )
    run_id: str = Field(
        validation_alias="runId",
        serialization_alias="runId",
        max_length=MAX_PROJECTION_ID_CHARS,
    )
    entries: tuple[AgUiResumeEntry, ...] = Field(
        default=(),
        validation_alias="resume",
        serialization_alias="resume",
        max_length=MAX_RESUME_ENTRIES,
    )

    @field_validator("thread_id", "run_id")
    @classmethod
    def normalize_resume_identity(cls, value: str) -> str:
        return _required_text(value, "resume identity", MAX_PROJECTION_ID_CHARS)

    @property
    def idempotency_key(self) -> str:
        payload = [entry.model_dump(mode="json", by_alias=True) for entry in self.entries]
        payload.sort(key=lambda item: (item["interruptId"], item["status"]))
        encoded = json.dumps(
            {"threadId": self.thread_id, "runId": self.run_id, "resume": payload},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


def resume_run_id(run_id: str, entries: Iterable[AgUiResumeEntry]) -> str:
    """Return a deterministic successor run identity without changing state."""

    normalized = AgUiResumeRequest(thread_id="thread", run_id=run_id, entries=tuple(entries))
    return f"{normalized.run_id}:resume:{normalized.idempotency_key[:16]}"


@dataclass(frozen=True, slots=True)
class AgUiProjection:
    """Projected AG-UI events and the exact durable cursor used for replay."""

    events: tuple[Event, ...]
    next_cursor: AgUiCursor | None
    replayed_from: AgUiCursor | None = None
