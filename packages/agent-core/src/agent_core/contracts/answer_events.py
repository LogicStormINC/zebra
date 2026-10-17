"""Committed answer event contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RequestedVersionScopePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)


class CheckedVersionScopePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=64)
    versions: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(max_length=12)
    source_refs: list[Annotated[str, Field(min_length=1, max_length=2048)]] = Field(max_length=32)
    basis: Literal["cited_fetched_source_version_only"]


class UnresolvedVersionScopePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=64)
    requested_version: str = Field(min_length=1, max_length=32)
    reason: Literal["requested_version_scope_not_established"]
    observed_versions: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(
        max_length=12)


class VersionScopeReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_scope: list[RequestedVersionScopePayload] = Field(max_length=12)
    checked_scope: list[CheckedVersionScopePayload] = Field(max_length=12)
    unresolved_points: list[UnresolvedVersionScopePayload] = Field(max_length=12)
    status: Literal["partial", "matched"]
    semantic_coverage_certified: Literal[False] = False

    @model_validator(mode="after")
    def validate_scope_correspondence(self) -> "VersionScopeReportPayload":
        expected = {
            (scope.subject.casefold(), scope.version) for scope in self.requested_scope
            if not any(checked.subject.casefold() == scope.subject.casefold()
                       and scope.version in checked.versions for checked in self.checked_scope)
        }
        actual = {(scope.subject.casefold(), scope.requested_version)
                  for scope in self.unresolved_points}
        if expected != actual or bool(expected) != (self.status == "partial"):
            raise ValueError("version scope status must match checked ranges and unresolved points")
        return self


class DeliveryAssessmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    satisfied: list[str] = Field(default_factory=list)
    unmet: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    media_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    task_type: str | None = None
    goal: str | None = None
    required_outcomes: list[str] = Field(default_factory=list)
    version_scope: VersionScopeReportPayload | None = None

    @model_validator(mode="after")
    def reject_complete_with_partial_version_scope(self) -> "DeliveryAssessmentPayload":
        if (self.status == "complete" and self.version_scope is not None
                and self.version_scope.status != "matched"):
            raise ValueError("complete delivery cannot have unresolved version scope")
        return self

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
