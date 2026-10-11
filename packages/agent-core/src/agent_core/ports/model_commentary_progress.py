"""Small durable pending publication identity; source text stays in canonical storage."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.contracts.model_commentary import MAX_COMMENTARY_CHUNKS


class PendingModelCommentary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_sequence: int = Field(ge=0, lt=2**63)
    attempt_number: int = Field(ge=1)
    model_call_id: str = Field(min_length=1, max_length=160)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_ids: list[str] = Field(min_length=1, max_length=MAX_COMMENTARY_CHUNKS)
    chunk_hashes: list[str] = Field(min_length=1, max_length=MAX_COMMENTARY_CHUNKS)
    next_index: int = Field(default=0, ge=0, lt=MAX_COMMENTARY_CHUNKS)

    @model_validator(mode="after")
    def exact_frontier(self) -> "PendingModelCommentary":
        if len(self.output_ids) != len(self.chunk_hashes) or self.next_index >= len(
            self.output_ids
        ):
            raise ValueError("invalid pending commentary frontier")
        return self
