"""Explicit frozen strict Task identity; no inference or runtime activation."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from agent_core.domain.coverage_contracts import CoverageContract, CoverageModel, CoverageName
from agent_core.domain.coverage_execution import CoverageExecutionBudget
from agent_core.domain.host_authority import MAX_MODEL_TOKENS, MAX_RUNTIME_SECONDS, HostResourceRef

CoverageValidationMode = Literal["eager", "final_certification"]


def coverage_admission_input(value: object) -> object:
    """Reconstruct raw fields, including extras, rather than trust typed copies.

    model_dump can discard unknown attributes and model_validate can trust nested
    instances. Walking stored fields makes both forged forms fail closed.
    """
    if isinstance(value, BaseModel):
        if value.__pydantic_extra__ or value.__dict__.keys() - type(value).model_fields.keys():
            raise ValueError("coverage admission typed input carries unknown attributes")
        return coverage_admission_input(value.__dict__)
    if isinstance(value, dict):
        return {key: coverage_admission_input(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return tuple(coverage_admission_input(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool | datetime | UUID):
        return value
    raise ValueError("unsupported coverage admission input type")


class CoverageTaskAdmission(CoverageModel):
    contract: CoverageContract
    history_ref: CoverageName | None = Field(default=None, exclude_if=lambda v: v is None)
    source_ref: HostResourceRef | None = Field(default=None, exclude_if=lambda v: v is None)
    model_profile: CoverageName
    # Keep historical canonical JSON/digests unchanged; fast mode is explicit admission.
    validation_mode: CoverageValidationMode = Field(
        default="eager", exclude_if=lambda value: value == "eager"
    )
    execution_budget: CoverageExecutionBudget
    # ponytail: v1 uses the existing attempt ceiling; no separate quota framework.
    max_model_calls: int = Field(strict=True, ge=1, le=1_000_000)
    max_model_tokens: int = Field(strict=True, ge=1, le=MAX_MODEL_TOKENS)
    max_runtime_seconds: int = Field(strict=True, ge=1, le=MAX_RUNTIME_SECONDS)

    @model_validator(mode="before")
    @classmethod
    def reconstruct_fields(cls, value: object) -> object:
        return coverage_admission_input(value)

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.contract.schema_version == 1:
            if self.history_ref is None or self.source_ref is not None:
                raise ValueError("v1 requires history_ref only")
        elif (
            self.history_ref is not None
            or self.source_ref is None
            or self.source_ref.resource_type != self.contract.source_definition.resource_type
        ):
            raise ValueError("v2 requires matching source_ref only")
        return self

    @property
    def source_resource(self) -> HostResourceRef:
        if self.source_ref is not None:
            return self.source_ref
        assert self.history_ref is not None
        return HostResourceRef(
            type=self.contract.source_definition.resource_type, id=self.history_ref
        )
