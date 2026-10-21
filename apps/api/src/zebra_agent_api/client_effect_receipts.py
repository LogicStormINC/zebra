"""Client effect receipt routes (submit / get)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_control_plane.client_effects import ClientEffectReceiptService
from agent_core.domain.client_effects import (
    ClientEffectError,
    ClientEffectReceipt,
    ClientEffectRequest,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import ClientEffectId, ClientSessionId
from agent_security.host_grant import VerifiedHostGrant

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.client_grant_auth import ClientAuthContext
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.tenant_guard import host_list_context_response, task_access_response


def submit_client_effect_receipt(
    app: ZebraAgentApi,
    effect_id: str,
    body: dict[str, Any],
    *,
    client_session_id: ClientSessionId,
    fence_token: str,
    controller: bool,
    idempotency_key: str,
    host_context: HostContextEnvelope | None = None,
    verified_host_grant: VerifiedHostGrant | None = None,
) -> ApiResponse:
    try:
        parsed_effect_id = ClientEffectId(UUID(effect_id))
    except ValueError:
        return ApiResponse(400, {"status": "invalid", "reason": "invalid_effect_id"})
    platform = app.client_platform
    if (
        platform is None
        or platform.client_effect_receipts is None
        or platform.client_effects is None
    ):
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    effect = platform.client_effects.get_effect(parsed_effect_id)
    if effect is None:
        return ApiResponse(404, {"status": "not_found", "reason": "unknown_effect"})
    if effect.client_session_id != client_session_id:
        return ApiResponse(404, {"status": "not_found", "reason": "unknown_effect"})
    denied = _effect_access_response(app, effect, host_context, verified_host_grant)
    if denied is not None:
        return denied
    try:
        receipt = ClientEffectReceipt.model_validate(
            {
                **body,
                "effect_id": effect_id,
                "idempotency_key": idempotency_key,
                "request_digest": effect.request_digest,
            }
        )
    except ValueError as exc:
        return ApiResponse(400, {"status": "invalid", "reason": str(exc)[:256]})
    try:
        acceptance = ClientEffectReceiptService(platform.client_effect_receipts).submit(
            receipt,
            request_fence_hash=_request_fence_hash(fence_token),
            session_id=effect.parent_session_id,
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


def get_client_effect(
    app: ZebraAgentApi,
    effect_id: str,
    *,
    auth: ClientAuthContext,
    host_context: HostContextEnvelope | None = None,
    verified_host_grant: VerifiedHostGrant | None = None,
) -> ApiResponse:
    try:
        parsed_effect_id = ClientEffectId(UUID(effect_id))
    except ValueError:
        return ApiResponse(400, {"status": "invalid", "reason": "invalid_effect_id"})
    platform = app.client_platform
    if platform is None or platform.client_effects is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    effect = platform.client_effects.get_effect(parsed_effect_id)
    if effect is None:
        return ApiResponse(404, {"status": "not_found", "reason": "unknown_effect"})
    if effect.client_session_id != auth.client_session_id:
        return ApiResponse(404, {"status": "not_found", "reason": "unknown_effect"})
    denied = _effect_access_response(app, effect, host_context, verified_host_grant)
    if denied is not None:
        return denied
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


def list_pending_client_effects(
    app: ZebraAgentApi,
    *,
    auth: ClientAuthContext,
    host_context: HostContextEnvelope | None = None,
    verified_host_grant: VerifiedHostGrant | None = None,
) -> ApiResponse:
    platform = app.client_platform
    if platform is None or platform.client_effects is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    denied = _effect_access_response(app, None, host_context, verified_host_grant)
    if denied is not None:
        return denied
    effects = platform.client_effects.list_pending(auth.client_session_id, limit=50)
    visible = []
    # ponytail: at most50 candidates, deduplicate Task/Run reads within this request;
    # no cross-request authority cache. A scoped storage cursor is a later extension.
    checks: dict[tuple[str, str], ApiResponse | None] = {}
    for effect in effects:
        if effect.client_session_id != auth.client_session_id:
            continue
        key = (str(effect.task_id), effect.run_id)
        if key not in checks:
            checks[key] = _effect_access_response(app, effect, host_context, verified_host_grant)
        denied = checks[key]
        if denied is not None:
            if denied.status_code == 404:
                continue
            return denied
        visible.append(effect)
    return ApiResponse(
        200,
        {
            "effects": [
                {
                    "effect_id": str(effect.effect_id),
                    "task_id": str(effect.task_id),
                    "run_id": effect.run_id,
                    "surface_instance_id": str(effect.client_session_id),
                    "action_name": effect.action_name,
                    "arguments": effect.arguments,
                    "status": effect.status.value,
                    "expected_ui_revision": effect.expected_ui_revision,
                    "expires_at": effect.expires_at.isoformat(),
                    "deadline": effect.expires_at.isoformat(),
                    "request_digest": effect.request_digest,
                    "action_contract_digest": effect.action_contract_digest,
                    "capability_version": effect.action_contract_digest,
                    "client_binding_digest": effect.client_binding_digest,
                    "idempotency_key": effect.idempotency_key,
                    "execution_location": "client",
                }
                for effect in visible
            ]
        },
    )


def _request_fence_hash(fence_token: str) -> str:
    import hashlib

    return hashlib.sha256(fence_token.encode()).hexdigest()


def _effect_access_response(
    app: ZebraAgentApi,
    effect: ClientEffectRequest | None,
    host_context: HostContextEnvelope | None,
    verified_host_grant: VerifiedHostGrant | None,
) -> ApiResponse | None:
    """Session possession never widens the current cloud Task/Run authority."""
    if app.settings.deployment != "cloud":
        return None
    if host_context is None:
        return ApiResponse(401, {"status": "unauthorized", "reason": "host_grant_required"})
    denied = host_list_context_response(host_context, verified_host_grant)
    if denied is None and effect is not None:
        denied = task_access_response(
            app,
            str(effect.task_id),
            host_context,
            verified_host_grant=verified_host_grant,
            run_id=effect.run_id,
        )
    if denied is not None and denied.status_code == 404:
        return ApiResponse(404, {"status": "not_found", "reason": "unknown_effect"})
    return denied
