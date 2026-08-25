"""Client effect application services (ADR-CLIENT-01).

Builds durable effect requests from a binding plus the worker lease
fence, and submits controller receipts through the atomic receipt port.
The service itself stays storage-free: every rule below is checked
before the port's single transaction runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_core.domain.client_effects import (
    ClientEffectContinuation,
    ClientEffectReceipt,
    ClientEffectRequest,
    client_effect_idempotency_key,
)
from agent_core.domain.client_run_bindings import ClientRunBinding
from agent_core.domain.client_sessions import ClientObserverActionError
from agent_core.domain.identifiers import SessionId, ToolCallId, new_client_effect_id
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
