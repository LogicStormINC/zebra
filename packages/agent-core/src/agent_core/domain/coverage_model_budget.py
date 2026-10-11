"""Frozen MODEL ledger values; receipts originate at the configured gateway boundary.

The composition must explicitly support the profile and prove a bound for the
complete request plus maximum output before transport. An input token estimate
is not that proof or an exact provider quota. Unknown profiles are unsupported.
Hidden gateway retries must be disabled by future composition.
"""

from datetime import timedelta
from typing import Self
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from agent_core.domain.coverage_contracts import (
    CoverageArtifactRef,
    CoverageCount,
    CoverageDigest,
    CoverageModel,
    CoverageName,
    CoverageTime,
)
from agent_core.domain.coverage_task_admission import (
    CoverageValidationMode,
    coverage_admission_input,
)
from agent_core.domain.coverage_validation import CoverageUnitKey


class CoverageBudgetValue(CoverageModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def reconstruct(cls, value: object) -> object:
        return coverage_admission_input(value)


class CoverageModelPolicy(CoverageBudgetValue):
    admission_event_digest: CoverageDigest
    admission_digest: CoverageDigest
    task_binding_digest: CoverageDigest
    model_profile: CoverageName
    validation_mode: CoverageValidationMode = Field(
        default="eager", exclude_if=lambda value: value == "eager"
    )
    max_calls: int = Field(strict=True, ge=1, le=1_000_000)
    max_tokens: int = Field(strict=True, ge=1)
    max_runtime_seconds: int = Field(strict=True, ge=1)
    started_at: CoverageTime
    deadline: CoverageTime

    @model_validator(mode="after")
    def validate_deadline(self) -> Self:
        if self.deadline != self.started_at + timedelta(seconds=self.max_runtime_seconds):
            raise ValueError("model deadline must be the original admission deadline")
        return self


class CoverageModelReservation(CoverageBudgetValue):
    reservation_key: CoverageName
    admission_digest: CoverageDigest
    key: CoverageUnitKey
    request_digest: CoverageDigest
    model_profile: CoverageName
    # Caller-proven full request/output bound; never an inferred input estimate.
    token_bound: int = Field(strict=True, ge=1)


class CoverageModelUsageReceipt(CoverageBudgetValue):
    reservation: CoverageModelReservation
    input_tokens: CoverageCount
    output_tokens: CoverageCount
    total_tokens: CoverageCount
    checkpoint_ref: CoverageArtifactRef | None = None
    checkpoint_digest: CoverageDigest | None = None

    @model_validator(mode="after")
    def validate_usage(self) -> Self:
        if (self.checkpoint_ref is None) != (self.checkpoint_digest is None):
            raise ValueError("checkpoint reference and digest must be paired")
        if self.checkpoint_ref is not None:
            if not self.checkpoint_ref.startswith("artifact://") or self.checkpoint_ref != (
                f"artifact://{UUID(self.checkpoint_ref.removeprefix('artifact://'))}"
            ):
                raise ValueError("checkpoint reference must be a canonical Artifact UUID")
        if (
            not self.input_tokens + self.output_tokens
            <= self.total_tokens
            <= self.reservation.token_bound
        ):
            raise ValueError("usage must cover input/output and fit the full reserved bound")
        return self


class CoverageModelReservationResult(CoverageBudgetValue):
    reservation: CoverageModelReservation
    event_watermark: int = Field(strict=True, ge=1)
    invoke: bool = Field(strict=True)
    receipt: CoverageModelUsageReceipt | None = None


class CoverageModelBudgetState(CoverageBudgetValue):
    policy: CoverageModelPolicy
    calls: CoverageCount
    charged_tokens: CoverageCount
    unresolved: CoverageCount
