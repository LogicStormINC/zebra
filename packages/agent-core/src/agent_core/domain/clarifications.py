from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.tools import ToolCall

MAX_CLARIFICATION_QUESTION_CHARS = 1_000
MAX_CLARIFICATION_CONTEXT_CHARS = 1_000
MAX_CLARIFICATION_CHOICES = 4
MAX_CLARIFICATION_CHOICE_CHARS = 200


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
