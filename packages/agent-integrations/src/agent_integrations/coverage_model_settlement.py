"""Consume the exact proof returned by atomic usage settlement, not a byte cache."""

from typing import TYPE_CHECKING

from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import decode_model_checkpoint
from agent_core.ports.coverage_model_budget import VerifiedCoverageModelSettlementPort

if TYPE_CHECKING:
    from agent_integrations.coverage_model_invocation import CoverageModelInvocation


def settle_checkpoint(
    invocation: "CoverageModelInvocation", receipt: CoverageModelUsageReceipt,
    body: bytes, *, settled: bool,
) -> None:
    """Validate the native settlement's exact original acknowledgement.

    Eager and legacy adapters retain their original final reread. A settlement
    return is usable only after the caller's fresh authority/deadline boundary.
    This internal MODEL response is not the final user report or certificate.
    The caller still rereads after its extensible post-settlement callbacks;
    these bytes do not prove availability after later external side effects.
    """
    store = invocation.store
    if settled:
        # reserve_model_call and the caller's current original reads already
        # validate exact replay. Do not open another settlement-only proof phase.
        return
    if invocation._defer_boundary_proof and isinstance(store, VerifiedCoverageModelSettlementPort):
        sequence, verified = store.settle_model_checkpoint(
            invocation.binding, receipt, fence=invocation._mutation_fence(),
        )
        if (type(sequence) is not int or sequence < 1
                or type(verified) is not bytes or verified != body):
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        checkpoint = decode_model_checkpoint(verified)
        if checkpoint.binding != invocation.binding:
            raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
        checkpoint.validate_receipt(receipt)
        return
    store.record_model_usage(invocation.binding, receipt, fence=invocation._mutation_fence())
