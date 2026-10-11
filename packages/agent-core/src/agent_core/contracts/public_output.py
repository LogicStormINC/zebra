"""Public communication, not private model reasoning or execution authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from re import fullmatch
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.contracts.model_commentary import ModelCommentaryChunk
from agent_core.domain.tools import ToolCallStatus, ToolReceipt, ToolResult

type EvidenceBasis = Literal["verified_work", "verified_result"]


@dataclass(frozen=True)
class PublicOutputPolicy:
    version: str = "2026-10-02.1"
    wait_seconds: float = 20.0
    max_outputs: int = 64
    max_characters: int = 4000
    delta_characters: int = 256
    delta_seconds: float = 0.1
    expression_max_calls: int = 0
    expression_deadline_seconds: float = 1.0
    expression_input_characters: int = 1600
    expression_output_tokens: int = 128

    def __post_init__(self) -> None:
        integers = (
            self.max_outputs,
            self.max_characters,
            self.delta_characters,
            self.expression_max_calls,
            self.expression_input_characters,
            self.expression_output_tokens,
        )
        if any(type(value) is not int for value in integers):
            raise ValueError("public output count budgets must be integers")
        if any(
            type(value) not in (int, float)
            for value in (self.wait_seconds, self.delta_seconds, self.expression_deadline_seconds)
        ):
            raise ValueError("public output timing budgets must be numeric")
        if (
            not isinstance(self.version, str)
            or not self.version.strip()
            or len(self.version) > 64
            or not 0 < self.wait_seconds <= 300
        ):
            raise ValueError("invalid public output pacing policy")
        if not 1 <= self.max_outputs <= 128 or not 128 <= self.max_characters <= 4000:
            raise ValueError("public output policy exceeds contract limits")
        if not 1 <= self.delta_characters <= 4096 or not 0 < self.delta_seconds <= 0.5:
            raise ValueError("invalid text flush budget")
        if not 0 <= self.expression_max_calls <= 2 or not 0 < self.expression_deadline_seconds <= 2:
            raise ValueError("invalid public expression call/deadline budget")
        if (
            not 1 <= self.expression_input_characters <= 2048
            or not 1 <= self.expression_output_tokens <= 128
        ):
            raise ValueError("invalid public expression token/input budget")


class AppliedReadScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["subscription_history", "event_detail"]
    source_scope: Literal["one_source", "all_entitled"]
    period_scope: Literal["one_period", "all_entitled"]
    date_from: int | None = Field(ge=-(2**63), lt=2**63)
    date_to: int | None = Field(ge=-(2**63), lt=2**63)
    keyword_filtered: bool
    market_filtered: bool


class PublicRecordRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=256)
    source_id: str = Field(min_length=1, max_length=256)

    @field_validator("event_id", "source_id")
    @classmethod
    def safe_identity(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("record identity must be nonblank and free of controls")
        return value


class PublicReadPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    offset: int = Field(ge=0, lt=2**63)
    limit: int = Field(ge=1, le=20)
    next_cursor: str | None = Field(default=None, max_length=128)


class PublicReadFacts(BaseModel):
    """Host-attested applied query evidence, never tool arguments or instructions."""

    model_config = ConfigDict(extra="forbid", strict=True)

    query_completed: Literal[True]
    query_result_kind: Literal["records", "count"] = "records"
    evidence_basis: EvidenceBasis
    applied_scope: AppliedReadScope
    summary: str = Field(min_length=1, max_length=1200)
    record_refs: list[PublicRecordRef] = Field(max_length=3)
    returned_count: int | None = Field(default=None, ge=0, le=20)
    total_count: int | None = Field(default=None, ge=0, lt=2**63)
    returned_source_count: int | None = Field(default=None, ge=0, le=20)
    eligible_source_count: int | None = Field(default=None, ge=0, lt=2**63)
    matched_source_count: int | None = Field(default=None, ge=0, lt=2**63)
    partial_sample: bool | None = None
    content_partial: bool | None = None
    page: PublicReadPage | None = None

    @field_validator("query_completed", mode="before")
    @classmethod
    def completed_query(cls, value: object) -> object:
        if value is not True:
            raise ValueError("query_completed must be exactly true")
        return value

    @model_validator(mode="after")
    def verified_evidence(self) -> PublicReadFacts:
        if not self.summary.strip() or type(self.query_completed) is not bool:
            raise ValueError("facts require a completed query and nonblank summary")
        if self.returned_count is not None and (
            len(self.record_refs) > self.returned_count
            or self.total_count is not None
            and self.total_count < self.returned_count
        ):
            raise ValueError("record/count evidence must be internally consistent")
        if self.query_result_kind == "count" and (
            self.record_refs or self.returned_count not in (None, 0)
        ):
            raise ValueError(
                "count query contract requires scalar count evidence, not a record page"
            )
        if (
            self.evidence_basis == "verified_result"
            and not self.record_refs
            and (
                self.total_count is None
                or self.total_count > 0
                and self.query_result_kind != "count"
            )
        ):
            raise ValueError(
                "result requires record evidence or an explicitly verified query count"
            )
        return self


class PublicOperationFacts(BaseModel):
    """Adapter-attested execution work, not a claim about the user's business goal."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["operation"]
    tool_call_id: str = Field(min_length=1, max_length=160)
    operation_completed: Literal[True]
    evidence_basis: Literal["verified_work"] = "verified_work"
    receipt: ToolReceipt
    output_truncated: bool

    @field_validator("tool_call_id")
    @classmethod
    def safe_identity(cls, value: str) -> str:
        return PublicRecordRef.safe_identity(value)

    @field_validator("operation_completed", mode="before")
    @classmethod
    def completed_operation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("operation_completed must be exactly true")
        return value

    @field_validator("receipt", mode="before")
    @classmethod
    def strict_receipt_scalars(cls, value: object) -> object:
        if isinstance(value, Mapping):
            scopes = value.get("scopes")
            if type(value.get("output_bytes")) is not int or not isinstance(scopes, list | tuple):
                raise ValueError("receipt requires integer output bytes and a scope sequence")
            if any(not isinstance(scope, str) for scope in scopes):
                raise ValueError("receipt scopes must be strings")
            if any(len(scope) > 256 or any(ord(char) < 32 for char in scope) for scope in scopes):
                raise ValueError("receipt scopes must be bounded and free of controls")
        return value

    @model_validator(mode="after")
    def completed_receipt(self) -> PublicOperationFacts:
        if self.receipt.status != "executed" or not fullmatch(
            r"[\w./:-]{1,256}", self.receipt.tool_name
        ):
            raise ValueError("operation facts require a completed, safely named tool receipt")
        if any(
            len(scope) > 256 or any(ord(char) < 32 for char in scope)
            for scope in self.receipt.scopes
        ):
            raise ValueError("receipt scopes must be bounded and free of controls")
        return self

    @property
    def summary(self) -> str:
        partial = "Returned output is partial. " if self.output_truncated else ""
        return (
            f"The `{self.receipt.tool_name}` execution receipt confirms completion and "
            f"{self.receipt.output_bytes} bytes of returned tool output. {partial}"
            "This verifies execution work, not completion of the user's business goal."
        )


def project_tool_result_evidence(
    result: ToolResult, *, output: str, metadata: Mapping[str, object]
) -> ToolResult:
    """Keep receipt provenance while recomputing derived, projected-output scalars."""
    receipt = result.receipt
    if receipt is not None:
        try:
            receipt = ToolReceipt.model_validate(
                {**receipt.as_metadata(), "output_bytes": len(output.encode("utf-8"))}
            )
        except ValueError:
            receipt = None  # An over-limit projection cannot acquire a fabricated byte bound.
    updated = dict(metadata)
    raw_facts = updated.get("public_facts")
    if isinstance(raw_facts, Mapping) and raw_facts.get("kind") == "operation":
        try:
            facts = PublicOperationFacts.model_validate(raw_facts)
            if (
                result.status is not ToolCallStatus.EXECUTED
                or facts.tool_call_id != str(result.tool_call_id)
                or facts.receipt != result.receipt
                or receipt is None
            ):
                raise ValueError("operation facts must match the original execution receipt")
            updated["public_facts"] = facts.model_copy(
                update={
                    "receipt": receipt,
                    "output_truncated": facts.output_truncated
                    or updated.get("output_truncated") is True,
                }
            ).model_dump(mode="json")
        except ValueError:
            updated.pop("public_facts", None)  # Never repair invalid evidence into a valid claim.
    return result.model_copy(update={"output": output, "metadata": updated, "receipt": receipt})


class PublicOutputPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    attempt_number: int = Field(ge=1)
    output_id: str = Field(min_length=1, max_length=160)
    kind: Literal["status", "commentary", "result"]
    phase: str = Field(min_length=1, max_length=64)
    origin: Literal["system", "model"]
    content: str = Field(min_length=1, max_length=4000)
    status: Literal["complete"] = "complete"
    meaningful: bool = False
    evidence_basis: EvidenceBasis | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    policy_version: str = Field(default="2026-10-02.1", max_length=64)
    model_call_id: str | None = Field(default=None, max_length=160)
    evidence_refs: list[str] = Field(default_factory=list, max_length=32)
    media_refs: list[str] = Field(default_factory=list, max_length=16)
    replaces_output_id: str | None = Field(default=None, max_length=160)
    commentary_chunk: ModelCommentaryChunk | None = None

    @model_validator(mode="after")
    def evidence_classification(self) -> PublicOutputPayload:
        if not self.content.strip() and self.commentary_chunk is None:
            raise ValueError("public output text must not be blank")
        if self.phase == "model_commentary" or self.commentary_chunk is not None:
            if (
                self.phase != "model_commentary"
                or self.commentary_chunk is None
                or self.kind != "commentary"
                or self.origin != "model"
                or self.meaningful
                or self.evidence_basis is not None
                or self.evidence_refs
                or self.media_refs
                or self.replaces_output_id is not None
                or not self.model_call_id
            ):
                raise ValueError("model commentary cannot assert evidence or final authority")
        if self.evidence_basis is not None:
            expected = "result" if self.evidence_basis == "verified_result" else "commentary"
            if self.kind != expected or not self.meaningful or not self.evidence_refs:
                raise ValueError("verified output requires matching kind and receipt provenance")
        return self

    @field_validator("output_id", "phase", "policy_version")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("public output text must not be blank")
        return value

    @field_validator("model_call_id", "replaces_output_id")
    @classmethod
    def optional_nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("public output IDs must not be blank")
        return value

    @field_validator("evidence_refs", "media_refs")
    @classmethod
    def bounded_refs(cls, value: list[str]) -> list[str]:
        if any(not ref.strip() or len(ref) > 2048 for ref in value):
            raise ValueError("public output references must be bounded and nonblank")
        return value
