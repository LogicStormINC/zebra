"""Subagent lifecycle and durable-delegation event payload contracts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class SubagentDelegatedPayload(BaseModel):
    """Join state frozen when a durable delegation suspends the parent.

    Mirrors the approval continuation payload: it carries the exact
    conversation, counters and tool-call identity needed to resume the
    parent with the child's real result once the wakeup arrives.
    """

    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    child_task_id: str
    tool_name: str
    tool_call_id: str
    arguments: dict[str, Any]
    assistant_message: str
    conversation: list[dict[str, Any]]
    model_calls_used: int
    tool_calls_executed: int
    provider_call_id: str | None = None

    @field_validator("attempt_number")
    @classmethod
    def ensure_positive_attempt(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("attempt_number must be positive")
        return value

    @field_validator("model_calls_used", "tool_calls_executed")
    @classmethod
    def ensure_non_negative_usage(cls, value: int) -> int:
        if value < 0:
            raise ValueError("delegation usage must not be negative")
        return value

    @field_validator("child_task_id", "tool_name", "tool_call_id", "assistant_message")
    @classmethod
    def ensure_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("delegation fields must not be blank")
        return normalized


class SubagentLifecyclePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    subagent_id: str
    status: str
    max_model_calls: int
    max_tool_calls: int
    max_depth: int
    model_calls_used: int = 0
    tool_calls_used: int = 0
    source_count: int = 0
    confidence: float = 0.0
    provenance: str

    @field_validator(
        "attempt_number",
        "max_model_calls",
        "max_tool_calls",
        "max_depth",
    )
    @classmethod
    def ensure_positive_count(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("subagent limits must be positive")
        return value

    @field_validator("model_calls_used", "tool_calls_used", "source_count")
    @classmethod
    def ensure_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("subagent usage must not be negative")
        return value

    @field_validator("subagent_id", "status", "provenance")
    @classmethod
    def ensure_text_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("subagent lifecycle fields must not be blank")
        return stripped

    @field_validator("confidence")
    @classmethod
    def ensure_confidence_in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("subagent confidence must be between zero and one")
        return value
