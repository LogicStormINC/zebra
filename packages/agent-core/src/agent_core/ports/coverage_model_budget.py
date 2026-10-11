"""Storage only; no model invocation or callback activation."""

from typing import Protocol, runtime_checkable

from agent_core.domain.coverage_model_budget import (
    CoverageModelBudgetState,
    CoverageModelPolicy,
    CoverageModelReservation,
    CoverageModelReservationResult,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.leases import LeaseFence


class CoverageModelBudgetStorePort(Protocol):
    def initialize_model_budget(
        self, binding: CoverageRunBinding, *, fence: LeaseFence
    ) -> CoverageModelPolicy: ...

    def reserve_model_call(
        self,
        binding: CoverageRunBinding,
        reservation: CoverageModelReservation,
        *,
        fence: LeaseFence,
    ) -> CoverageModelReservationResult: ...

    def record_model_usage(
        self, binding: CoverageRunBinding, receipt: CoverageModelUsageReceipt, *, fence: LeaseFence
    ) -> int: ...

    def model_budget_state(self, binding: CoverageRunBinding) -> CoverageModelBudgetState: ...


@runtime_checkable
class VerifiedCoverageModelSettlementPort(Protocol):
    """One atomic settlement returns its exact original checkpoint proof.

    Verify current tenant/Task/fence, canonical Event, bytes and retention, then
    settle or verify the identical settled receipt. Return only after successful
    transaction exit. No cached permissions or certificate is granted by these
    bytes. Extensible callbacks after the proof require a fresh original read;
    independent final certification must also reread the originals.
    """

    def settle_model_checkpoint(
        self, binding: CoverageRunBinding, receipt: CoverageModelUsageReceipt, *, fence: LeaseFence
    ) -> tuple[int, bytes]: ...
