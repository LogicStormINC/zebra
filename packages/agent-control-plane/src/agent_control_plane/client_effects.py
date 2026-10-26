"""Client effect application services (ADR-CLIENT-01).

Builds durable effect requests from a binding plus the worker lease
fence, and submits controller receipts through the atomic receipt port.
The service itself stays storage-free: every rule below is checked
before the port's single transaction runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from agent_core.domain.client_capabilities import (
    ClientActionContract,
    canonical_client_capability_digest,
)
from agent_core.domain.client_effects import (
    RECEIPT_TERMINAL_STATUSES,
    ClientEffectContinuation,
    ClientEffectReceipt,
    ClientEffectRequest,
    ClientEffectStatus,
    client_effect_idempotency_key,
)
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import ClientObserverActionError
from agent_core.domain.identifiers import SessionId, ToolCallId, new_client_effect_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.client_effect_receipts import (
    ClientEffectReceiptPort,
    ClientReceiptAcceptance,
)

DEFAULT_EFFECT_TTL = timedelta(minutes=10)


class ClientEffectServiceError(ValueError):
    pass


def build_client_effect_request(
    *,
    binding: ClientRunBinding,
    tool_call_id: ToolCallId,
    action_name: str,
    arguments: dict[str, object],
    action_contract_digest: str,
    fence_hash: str,
    expected_ui_revision: int,
    session_id: SessionId,
    effect_ttl: timedelta = DEFAULT_EFFECT_TTL,
) -> ClientEffectRequest:
    """Derive a schedule-only request pinned to the binding and fence."""

    binding.ensure_allows(action_name)
    now = datetime.now(UTC)
    return ClientEffectRequest(
        effect_id=new_client_effect_id(),
        task_id=binding.task_id,
        parent_session_id=session_id,
        run_id=binding.run_id,
        client_session_id=binding.client_session_id,
        tool_call_id=tool_call_id,
        action_name=action_name,
        arguments=dict(arguments),
        action_contract_digest=action_contract_digest,
        client_binding_digest=binding.binding_digest,
        fence_hash=fence_hash,
        expected_ui_revision=expected_ui_revision,
        idempotency_key=client_effect_idempotency_key(
            task_id=binding.task_id,
            run_id=binding.run_id,
            tool_call_id=tool_call_id,
        ),
        requested_at=now,
        expires_at=now + effect_ttl,
    )


def build_client_effect_continuation(
    request: ClientEffectRequest,
    *,
    assistant_message: str,
    model_calls_used: int,
    tool_calls_executed: int,
) -> ClientEffectContinuation:
    return ClientEffectContinuation(
        effect_id=request.effect_id,
        task_id=request.task_id,
        run_id=request.run_id,
        tool_call_id=request.tool_call_id,
        action_name=request.action_name,
        assistant_message=assistant_message,
        model_calls_used=model_calls_used,
        tool_calls_executed=tool_calls_executed,
        created_at=datetime.now(UTC),
    )


class ClientEffectReceiptService:
    """Receipt admission for the runtime API (controller-only)."""

    def __init__(self, receipts: ClientEffectReceiptPort) -> None:
        self._receipts = receipts

    def submit(
        self,
        receipt: ClientEffectReceipt,
        *,
        request_fence_hash: str,
        session_id: SessionId,
        controller: bool,
    ) -> ClientReceiptAcceptance:
        if not controller:
            raise ClientObserverActionError(
                "observers cannot submit receipts; only the active controller can"
            )
        return self._receipts.accept_receipt(
            receipt,
            request_fence_hash=request_fence_hash,
            session_id=session_id,
        )


def original_client_effect_result(
    call: ToolCall,
    original: ToolResult,
    *,
    binding: ClientRunBinding,
    contract: ClientActionContract,
    execution_session_id: SessionId,
    effect: ClientEffectRequest | None,
    receipt: ClientEffectReceipt | None,
) -> ToolResult | None:
    """Resolve the same business intent from its original evidence, never a new UI effect."""
    if effect is None or (
        str(effect.task_id) != str(binding.task_id)
        or effect.action_name != call.name
        or effect.tool_call_id != original.tool_call_id
        or call.name not in binding.allowed_actions
        or effect.arguments != call.arguments
        or effect.action_contract_digest
        != canonical_client_capability_digest(contract.model_dump(mode="json"))
        or str(effect.effect_id) != original.metadata.get("client_effect_id")
        or effect.request_digest != original.metadata.get("client_effect_request_digest")
        or effect.run_id != original.metadata.get("client_effect_run_id")
        or effect.client_binding_digest != original.metadata.get("client_effect_binding_digest")
    ):
        return None
    if receipt is None:
        # Exact original-operation recovery may still wait on its OWN currently bound Run.
        if (
            effect.parent_session_id == execution_session_id
            and effect.tool_call_id == call.tool_call_id
            and effect.run_id == binding.run_id
            and effect.client_binding_digest == binding.binding_digest
            and effect.status in {ClientEffectStatus.PENDING, ClientEffectStatus.DELIVERED}
        ):
            return original
        return None
    if (
        receipt.effect_id != effect.effect_id
        or receipt.request_digest != effect.request_digest
        or receipt.status not in RECEIPT_TERMINAL_STATUSES
    ):
        return None
    return ToolResult(
        tool_call_id=call.tool_call_id,
        status=ToolCallStatus.EXECUTED
        if receipt.status is ClientEffectStatus.SUCCEEDED
        else ToolCallStatus.FAILED,
        output=json.dumps(
            {
                "status": receipt.status.value,
                "result": receipt.result,
                "evidence_scope": "historical_business_effect",
                "current_ui_performed": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        metadata={
            "historical_client_effect": True,
            "original_client_effect_id": str(effect.effect_id),
            "original_client_effect_run_id": effect.run_id,
            "original_client_effect_receipt_id": str(receipt.receipt_id),
            "original_client_effect_status": receipt.status.value,
            "current_ui_performed": False,
        },
    )
