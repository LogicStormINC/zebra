"""Client effect receipt routes (submit / get)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_control_plane.client_effects import ClientEffectReceiptService
from agent_core.domain.client_effects import (
    ClientEffectError,
    ClientEffectReceipt,
)
from agent_core.domain.identifiers import ClientEffectId, SessionId

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.responses import ApiResponse


def submit_client_effect_receipt(
    app: ZebraAgentApi,
    effect_id: str,
    body: dict[str, Any],
    *,
    fence_token: str,
    controller: bool,
    idempotency_key: str,
) -> ApiResponse:
    platform = app.client_platform
    if (
        platform is None
        or platform.client_effect_receipts is None
        or platform.client_effects is None
    ):
        return ApiResponse(
            503, {"status": "unavailable", "reason": "client_integration_disabled"}
        )
    effect = platform.client_effects.get_effect(ClientEffectId(UUID(effect_id)))
    if effect is None:
        return ApiResponse(404, {"status": "not_found", "reason": "unknown_effect"})
    receipt = ClientEffectReceipt.model_validate(
        {
            **body,
            "effect_id": effect_id,
            "idempotency_key": idempotency_key,
            "request_digest": effect.request_digest,
        }
    )
    session_id = SessionId(UUID(str(effect.task_id)))
    try:
        acceptance = ClientEffectReceiptService(
            platform.client_effect_receipts
        ).submit(
            receipt,
            request_fence_hash=_request_fence_hash(fence_token),
            session_id=session_id,
            controller=controller,
        )
    except ClientEffectError as exc:
        status = 409
        reason = str(exc)[:256]
        if "fence" in reason:
            status, reason = 409, "stale_client_fence"
        elif "expired" in reason:
            status, reason = 410, "effect_expired"
        elif "revision" in reason:
            status, reason = 409, "stale_ui_revision"
        return ApiResponse(status, {"status": "rejected", "reason": reason})
    return ApiResponse(
        200,
        {
            "status": acceptance.receipt.status.value,
            "resume_command_id": acceptance.resume_command_id,
            "replayed": acceptance.replayed,
        },
    )


def get_client_effect(app: ZebraAgentApi, effect_id: str) -> ApiResponse:
    platform = app.client_platform
    if platform is None or platform.client_effects is None:
        return ApiResponse(
            503, {"status": "unavailable", "reason": "client_integration_disabled"}
        )
    effect = platform.client_effects.get_effect(ClientEffectId(UUID(effect_id)))
    if effect is None:
        return ApiResponse(404, {"status": "not_found", "reason": "unknown_effect"})
    return ApiResponse(
        200,
        {
            "effect_id": str(effect.effect_id),
            "action_name": effect.action_name,
            "status": effect.status.value,
            "expected_ui_revision": effect.expected_ui_revision,
            "expires_at": effect.expires_at.isoformat(),
            "request_digest": effect.request_digest,
        },
    )


def _request_fence_hash(fence_token: str) -> str:
    import hashlib

    return hashlib.sha256(fence_token.encode()).hexdigest()
