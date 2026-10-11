"""A publication plan for public assistant text, never evidence or private reasoning."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_COMMENTARY_CHUNKS = 8
COMMENTARY_CHUNK_CHARACTERS = 4000


class ModelCommentaryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    disposition: Literal["admitted", "quota_exhausted", "text_limit"]
    output_ids: list[str] = Field(default_factory=list, max_length=MAX_COMMENTARY_CHUNKS)
    chunk_characters: Literal[4000] = 4000
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def planned_not_published(self) -> "ModelCommentaryPlan":
        if (self.disposition == "admitted") != bool(self.output_ids):
            raise ValueError("commentary admission requires its exact chunk identities")
        if len(set(self.output_ids)) != len(self.output_ids) or any(
            not key or len(key) > 160 for key in self.output_ids
        ):
            raise ValueError("invalid commentary output identities")
        return self


class ModelCommentaryChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    index: int = Field(ge=0, lt=MAX_COMMENTARY_CHUNKS)
    count: int = Field(ge=1, le=MAX_COMMENTARY_CHUNKS)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def within_source(self) -> "ModelCommentaryChunk":
        if self.index >= self.count:
            raise ValueError("commentary chunk exceeds source plan")
        return self
