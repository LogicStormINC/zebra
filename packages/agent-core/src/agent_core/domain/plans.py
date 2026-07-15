from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_PLAN_STEPS = 12
MAX_PLAN_STEP_ID_CHARS = 64
MAX_PLAN_STEP_CONTENT_CHARS = 240


class PlanStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str = Field(min_length=1, max_length=MAX_PLAN_STEP_ID_CHARS)
    content: str = Field(min_length=1, max_length=MAX_PLAN_STEP_CONTENT_CHARS)
    status: PlanStepStatus

    @field_validator("step_id", "content")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("plan step text must not be blank")
        return normalized


class SessionPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: tuple[PlanStep, ...] = Field(default=(), max_length=MAX_PLAN_STEPS)
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_plan(self) -> "SessionPlan":
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("plan step identifiers must be unique")
        if sum(step.status is PlanStepStatus.IN_PROGRESS for step in self.steps) > 1:
            raise ValueError("plan must contain at most one in-progress step")
        if self.updated_at is not None and self.updated_at.tzinfo is None:
            raise ValueError("plan updated_at must be timezone-aware")
        return self

    @property
    def summary(self) -> dict[str, int]:
        counts = {status.value: 0 for status in PlanStepStatus}
        for step in self.steps:
            counts[step.status.value] += 1
        return {
            "total": len(self.steps),
            "pending": counts[PlanStepStatus.PENDING.value],
            "in_progress": counts[PlanStepStatus.IN_PROGRESS.value],
            "completed": counts[PlanStepStatus.COMPLETED.value],
            "cancelled": counts[PlanStepStatus.CANCELLED.value],
        }

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "steps": [step.model_dump(mode="json") for step in self.steps],
            "summary": self.summary,
        }
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at.isoformat()
        return payload
