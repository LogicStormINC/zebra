from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from agent_core.domain.context_capsule import ContextCapsule


class ContextCompactedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    before_tokens: int
    after_tokens: int
    removed_message_count: int
    retained_message_count: int
    within_budget: bool
    provenance: str
    capsule: ContextCapsule | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @field_serializer("capsule")
    def serialize_capsule(self, value: ContextCapsule | None) -> dict[str, object] | None:
        return value.model_dump(mode="json") if value is not None else None

    @field_validator("attempt_number")
    @classmethod
    def ensure_positive_attempt_number(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("attempt_number must be positive")
        return value

    @field_validator(
        "before_tokens",
        "after_tokens",
        "removed_message_count",
        "retained_message_count",
    )
    @classmethod
    def ensure_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("compaction counts must not be negative")
        return value

    @field_validator("provenance")
    @classmethod
    def ensure_provenance_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("provenance must not be blank")
        return stripped
