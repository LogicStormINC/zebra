"""Published checks and validated observations; model prose cannot certify a run."""

from typing import Literal, Self

from pydantic import Field, model_validator

from agent_core.domain.coverage_contracts import (
    CoverageCheck,
    CoverageDigest,
    CoverageModel,
    CoverageName,
    coverage_digest,
)
from agent_core.domain.coverage_validation import CoverageUnitKey


class CoverageExecutionBudget(CoverageModel):
    max_attempts: int = Field(strict=True, ge=1, le=1000000)
    max_input_bytes: int = Field(strict=True, ge=0)


class CoverageQuote(CoverageModel):
    part_id: CoverageName
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, ge=1)
    text: str = Field(min_length=1, max_length=4096)


class CoverageObservation(CoverageModel):
    key: CoverageUnitKey
    outcome: Literal["clear", "finding"]
    summary: str = Field(min_length=1, max_length=4096)
    quotes: tuple[CoverageQuote, ...] = Field(default=(), max_length=100)
    part_result_digests: tuple[CoverageDigest, ...] = Field(default=(), max_length=4096)

    @model_validator(mode="after")
    def require_evidence(self) -> Self:
        if self.key.kind == "part" and self.part_result_digests:
            raise ValueError("part observations cannot claim merged evidence")
        if self.outcome == "finding" and not self.quotes:
            raise ValueError("a finding requires source evidence")
        return self

    @property
    def digest(self) -> str:
        return coverage_digest(self.model_dump(mode="json"))

    def validate_source(self, bodies: dict[str, str]) -> None:
        for quote in self.quotes:
            body = bodies.get(quote.part_id)
            if (
                body is None
                or not quote.start < quote.end <= len(body)
                or body[quote.start : quote.end] != quote.text
            ):
                raise ValueError("coverage quote does not match the immutable source")
            if self.key.kind == "part" and quote.part_id != self.key.part_id:
                raise ValueError("part observation refers to another part")


class PublishedCoverageCheck(CoverageModel):
    """The caller freezes this definition before admission, never from chat text."""

    id: CoverageName
    version: CoverageName
    kind: Literal["program", "model"]
    implementation: Literal["literal_contains/1", "structured_model/1"]
    terms: tuple[str, ...] = Field(default=(), max_length=100)
    model_profile: CoverageName | None = None
    instructions: str = Field(default="", max_length=12000)
    max_part_characters: int = Field(default=12000, strict=True, ge=1, le=100000)

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.implementation == "literal_contains/1":
            if (
                self.kind != "program"
                or not self.terms
                or any(not term or len(term) > 4096 for term in self.terms)
                or self.model_profile is not None
            ):
                raise ValueError("literal check requires explicit bounded terms")
        elif self.kind != "model" or self.model_profile is None or not self.instructions:
            raise ValueError("model check requires a frozen profile and instructions")
        return self

    @property
    def contract_check(self) -> CoverageCheck:
        return CoverageCheck(
            id=self.id,
            version=self.version,
            kind=self.kind,
            definition_digest=coverage_digest(self.model_dump(mode="json")),
        )
