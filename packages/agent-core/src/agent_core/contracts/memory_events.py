from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MemoryContextSelectedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_count: int = Field(ge=0, le=50)
    memory_ids: list[str] = Field(default_factory=list, max_length=50)
    query_has_text: bool
    mode: str

    @model_validator(mode="after")
    def require_consistent_selection(self) -> Self:
        normalized = [item.strip() for item in self.memory_ids]
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("memory_ids must contain unique non-blank IDs")
        if self.selected_count != len(normalized):
            raise ValueError("selected_count must match memory_ids")
        self.memory_ids = normalized
        return self


class MemoryExtractionCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completion_revision: int = Field(ge=0)
    candidate_count: int = Field(ge=0, le=500)
    lifecycle_count: int = Field(ge=0, le=500)
    outcome: str

    @field_validator("outcome")
    @classmethod
    def require_known_outcome(cls, value: str) -> str:
        if value not in {"no_eligible_memory", "committed"}:
            raise ValueError("unknown Memory extraction outcome")
        return value
