from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.tools import ToolCall

MAX_CLARIFICATION_QUESTION_CHARS = 1_000
MAX_CLARIFICATION_CONTEXT_CHARS = 1_000
MAX_CLARIFICATION_CHOICES = 4
MAX_CLARIFICATION_CHOICE_CHARS = 200
MAX_ELICITATION_SCHEMA_BYTES = 8_192
DEFAULT_CLARIFICATION_SOURCE = "agent.clarify"
MCP_ELICITATION_SOURCE = "mcp.elicitation"


class ClarificationContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    clarification_id: str
    tool_call_id: str
    provider_call_id: str | None = None
    question: str = Field(max_length=MAX_CLARIFICATION_QUESTION_CHARS)
    choices: tuple[str, ...] = Field(default=(), max_length=MAX_CLARIFICATION_CHOICES)
    context: str | None = Field(default=None, max_length=MAX_CLARIFICATION_CONTEXT_CHARS)
    assistant_message: str
    requested_at: datetime
    # Optional typed response schema (MCP elicitation `requestedSchema`). None means
    # the default agent.clarify flow and is excluded from serialization.
    response_schema: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # Origin of the clarification; None == DEFAULT_CLARIFICATION_SOURCE ("agent.clarify").
    elicitation_source: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("clarification_id", "tool_call_id", "question", "assistant_message")
    @classmethod
    def ensure_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("clarification fields must not be blank")
        return normalized

    @field_validator("provider_call_id", "context")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("optional clarification fields must not be blank")
        return normalized

    @field_validator("choices")
    @classmethod
    def normalize_choices(cls, choices: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(choice.strip() for choice in choices)
        if any(not choice for choice in normalized):
            raise ValueError("clarification choices must not be blank")
        if any(len(choice) > MAX_CLARIFICATION_CHOICE_CHARS for choice in normalized):
            raise ValueError("clarification choices are too long")
        if len({choice.casefold() for choice in normalized}) != len(normalized):
            raise ValueError("clarification choices must be unique")
        return normalized

    @field_validator("response_schema")
    @classmethod
    def bound_response_schema(cls, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        if schema is None:
            return None
        if not isinstance(schema, dict):
            raise ValueError("response_schema must be an object")
        import json

        if len(json.dumps(schema, separators=(",", ":")).encode()) > MAX_ELICITATION_SCHEMA_BYTES:
            raise ValueError("response_schema exceeds the size limit")
        return schema

    @field_validator("elicitation_source")
    @classmethod
    def normalize_elicitation_source(cls, source: str | None) -> str | None:
        if source is None:
            return None
        normalized = source.strip()
        if not normalized:
            raise ValueError("elicitation_source must not be blank")
        return normalized

    @model_validator(mode="after")
    def ensure_requested_at_is_aware(self) -> "ClarificationContext":
        if self.requested_at.tzinfo is None:
            raise ValueError("clarification requested_at must be timezone-aware")
        return self

    @classmethod
    def from_tool_call(
        cls,
        tool_call: ToolCall,
        *,
        assistant_message: str,
        requested_at: datetime,
    ) -> "ClarificationContext":
        arguments = tool_call.arguments
        question = arguments.get("question")
        choices = arguments.get("choices", ())
        context = arguments.get("context")
        if not isinstance(question, str):
            raise ValueError("agent.clarify requires 'question' to be a string")
        if not isinstance(choices, list | tuple) or any(
            not isinstance(choice, str) for choice in choices
        ):
            raise ValueError("agent.clarify requires 'choices' to be an array of strings")
        if context is not None and not isinstance(context, str):
            raise ValueError("agent.clarify requires 'context' to be a string when provided")
        tool_call_id = str(tool_call.tool_call_id)
        return cls(
            clarification_id=tool_call_id,
            tool_call_id=tool_call_id,
            provider_call_id=tool_call.provider_call_id,
            question=question,
            choices=tuple(choices),
            context=context,
            assistant_message=assistant_message,
            requested_at=requested_at,
        )

    def to_mapping(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)

    @property
    def effective_source(self) -> str:
        return self.elicitation_source or DEFAULT_CLARIFICATION_SOURCE

    @classmethod
    def from_elicitation(
        cls,
        *,
        message: str,
        requested_schema: dict[str, Any] | None,
        tool_call_id: str,
        assistant_message: str,
        requested_at: datetime,
    ) -> "ClarificationContext":
        if not isinstance(message, str) or not message.strip():
            raise ValueError("elicitation requires a non-blank 'message'")
        if requested_schema is not None and not isinstance(requested_schema, dict):
            raise ValueError("elicitation 'requestedSchema' must be an object when provided")
        normalized_id = str(tool_call_id)
        return cls(
            clarification_id=normalized_id,
            tool_call_id=normalized_id,
            question=message.strip(),
            choices=(),
            response_schema=requested_schema,
            elicitation_source=MCP_ELICITATION_SOURCE,
            assistant_message=assistant_message,
            requested_at=requested_at,
        )
