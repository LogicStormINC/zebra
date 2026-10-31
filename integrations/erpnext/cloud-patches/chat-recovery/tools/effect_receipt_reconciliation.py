from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from agent_core.domain.effect_dispatch import (
    EffectDispatch,
    EffectEvidence,
    EffectResolutionOutcome,
)
from agent_core.domain.host_effect_receipts import HostEffectReceipt, HostEffectStatus
from agent_core.domain.tools import ToolCallStatus, ToolResult

if TYPE_CHECKING:
    from agent_tools.effect_guard import FencedEffectToolGateway


def reconcile_uncertain_effects(self: FencedEffectToolGateway, *, limit: int = 100) -> int:
    self._ownership_check()
    list_uncertain = getattr(self._dispatch, "list_uncertain", None)
    resolver = getattr(self._gateway, "reconcile_effect_receipt", None)
    if not callable(list_uncertain) or not callable(resolver):
        return 0
    dispatches: tuple[EffectDispatch, ...] = list_uncertain(
        self._execution_session_id,
        current_fence=self._fence,
        limit=limit,
    )
    resolved = 0
    for dispatch in dispatches:
        self._ownership_check()
        evidence = dispatch.evidence
        receipt = None if evidence is None else evidence.host_effect_receipt
        if receipt is None:
            continue
        settled: HostEffectReceipt = resolver(receipt)
        if not settled.reconciled:
            continue
        tool_call = self._read_tool_call(dispatch.payload_artifact_ref)
        result = ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=(
                ToolCallStatus.EXECUTED
                if settled.effect_status is HostEffectStatus.SUCCEEDED
                else ToolCallStatus.FAILED
            ),
            output="Host Effect reconciled from its durable receipt.",
            metadata={
                "provider_operation_id": settled.provider_operation_id,
                "business_revision": settled.business_revision,
                "business_outcome": (
                    "applied" if settled.effect_status is HostEffectStatus.SUCCEEDED else "rejected"
                ),
                "transport_outcome": "returned",
                "host_effect_receipt": settled.model_dump(mode="json"),
            },
        )
        with self._mutation_guard():
            terminal = self._terminal_event(tool_call, result)
            persisted = self._dispatch.resolve_uncertain(
                dispatch.dispatch_id,
                current_fence=self._fence,
                evidence=EffectEvidence(
                    reason_code="host_receipt_reconciled",
                    provider_operation_id_hash=sha256(
                        settled.provider_operation_id.encode()
                    ).hexdigest(),
                    host_effect_receipt=settled,
                ),
                outcome=(
                    EffectResolutionOutcome.SUCCEEDED
                    if settled.effect_status is HostEffectStatus.SUCCEEDED
                    else EffectResolutionOutcome.FAILED_NO_EFFECT
                ),
                terminal_event=terminal,
                result=(result if settled.effect_status is HostEffectStatus.SUCCEEDED else None),
            )
            self._accept_event(persisted)
        resolved += 1
    return resolved
