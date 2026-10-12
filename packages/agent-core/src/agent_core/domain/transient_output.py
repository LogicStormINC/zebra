"""Bounded, non-authoritative text transport; never a SessionEvent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId, TurnId

MAX_TRANSIENT_FRAME_BYTES = 16 * 1024


class TransientGeneration(BaseModel):
    """One server-bound model invocation; retries must create a new generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: TaskId
    segment_id: SessionId
    turn_id: TurnId
    run_id: str = Field(min_length=1, max_length=128)
    attempt_number: int = Field(strict=True, ge=1)
    model_call_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=256)
    generation_id: str = Field(min_length=1, max_length=128)
    lease_fence: int = Field(strict=True, ge=1)

    @model_validator(mode="after")
    def require_existing_message_identity(self) -> TransientGeneration:
        if self.message_id != f"message:{self.model_call_id}":
            raise ValueError("message_id must match message:{model_call_id}")
        return self

    @field_validator("run_id", "model_call_id", "generation_id", "message_id")
    @classmethod
    def require_trimmed_identity(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("transient identities must be trimmed and contain no controls")
        return value


class TransientTextFrame(TransientGeneration):
    """Flat wire v2 frame. Namespace and authorization are intentionally absent."""

    version: Literal[2] = 2
    kind: Literal["text_delta"] = "text_delta"
    presentation: Literal["provisional_draft"] = "provisional_draft"
    offset: int = Field(strict=True, ge=0)
    content_delta: str = Field(min_length=1)
    durable_anchor: int = Field(strict=True, ge=0)

    @field_validator("version", mode="before")
    @classmethod
    def require_integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("version must be an integer")
        return value

    @model_validator(mode="after")
    def require_bounded_wire(self) -> TransientTextFrame:
        if len(self.wire_bytes()) > MAX_TRANSIENT_FRAME_BYTES:
            raise ValueError("transient frame exceeds 16KiB UTF-8 JSON budget")
        return self

    def wire_bytes(self) -> bytes:
        """Exact compact JSON transport bytes, including every identity field."""
        return self.model_dump_json().encode("utf-8")

    @property
    def generation(self) -> TransientGeneration:
        return TransientGeneration.model_validate(
            self.model_dump(include=set(TransientGeneration.model_fields))
        )


def transient_category_allowed(
    *,
    event_type: EventType,
    category: str | None = None,
    response_stage: str | None = None,
    coverage_mode: bool = True,
) -> bool:
    """Closed classification only, NOT publication authorization.

    Trusted composition supplies the category for a verified ordinary public
    on_text_delta callback at call admission. Missing purpose/coverage context
    fails closed. Candidate/tool-loop public text may be a labelled draft;
    reasoning/private/coverage/public_expression remain prohibited. This does
    not authorize final delivery or bypass ANSWER_COMMITTED publication gates.
    """
    return (
        event_type is EventType.MODEL_RESPONSE_DELTA
        and category == "ordinary_public_text"
        and response_stage in (None, "candidate", "tool_loop")
        and coverage_mode is False
    )
