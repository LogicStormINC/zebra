"""Committed answer event contracts."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeliveryAssessmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    satisfied: list[str] = Field(default_factory=list)
    unmet: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    task_type: str | None = None
    goal: str | None = None
    required_outcomes: list[str] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def ensure_known_status(cls, value: str) -> str:
        if value not in {"complete", "partial", "blocked"}:
            raise ValueError("status must be complete, partial, or blocked")
        return value

    @field_validator("task_type")
    @classmethod
    def ensure_known_task_type(cls, value: str | None) -> str | None:
        if value is not None and value not in {"answer", "research", "change", "create", "operate"}:
            raise ValueError("task_type is not supported")
        return value

    @field_validator("goal")
    @classmethod
    def ensure_goal_is_bounded(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped or len(stripped) > 4_000:
            raise ValueError("goal must be non-blank and at most 4000 characters")
        return stripped


class AnswerCommittedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int = Field(gt=0)
    assistant_message: str
    delivery_assessment: DeliveryAssessmentPayload
    model_call_id: str | None = None

    @field_validator("assistant_message", "model_call_id")
    @classmethod
    def ensure_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped
