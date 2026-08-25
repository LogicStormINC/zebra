"""Client session runtime routes (open / heartbeat / mount)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_control_plane.client_admission import (
    ClientAdmissionError,
    ClientAdmissionService,
    ClientBindingService,
)
from agent_core.domain.client_capabilities import MountedCapabilitySnapshot
from agent_core.domain.client_sessions import (
    ClientSessionError,
    ClientSessionGrant,
)
from agent_core.domain.identifiers import ClientSessionId, TaskId

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.client_grant_auth import ClientAuthContext
from zebra_agent_api.responses import ApiResponse


def open_client_session(app: ZebraAgentApi, body: dict[str, Any]) -> ApiResponse:
    platform = app.client_platform
    if platform is None or platform.client_sessions is None:
        return ApiResponse(
            503, {"status": "unavailable", "reason": "client_integration_disabled"}
        )
    grant = ClientSessionGrant.model_validate(body.get("grant") or {})
    session = ClientAdmissionService(platform.client_sessions).open_session(grant)
    return ApiResponse(
        201,
        {
            "client_session_id": str(session.session_id),
            "status": session.status.value,
            "expires_at": session.expires_at.isoformat(),
        },
    )


def heartbeat_client_session(
    app: ZebraAgentApi, session_id: str
) -> ApiResponse:
    platform = app.client_platform
    if platform is None or platform.client_sessions is None:
        return ApiResponse(
            503, {"status": "unavailable", "reason": "client_integration_disabled"}
        )
    try:
        session = ClientAdmissionService(platform.client_sessions).heartbeat(
            ClientSessionId(_uuid(session_id))
        )
    except ClientSessionError:
        return ApiResponse(
            409, {"status": "expired", "reason": "client_session_expired"}
        )
    return ApiResponse(200, {"status": session.status.value})


def mount_client_session(
    app: ZebraAgentApi, session_id: str, body: dict[str, Any], auth: ClientAuthContext
) -> ApiResponse:
    platform = app.client_platform
    if platform is None or platform.client_sessions is None:
        return ApiResponse(
            503, {"status": "unavailable", "reason": "client_integration_disabled"}
        )
    snapshot = MountedCapabilitySnapshot.model_validate(body)
    if snapshot.client_session_id != ClientSessionId(_uuid(session_id)):
        return ApiResponse(
            409, {"status": "conflict", "reason": "session_id_mismatch"}
        )
    try:
        admission = ClientAdmissionService(platform.client_sessions).mount(
            ClientSessionId(_uuid(session_id)), snapshot
        )
    except (ClientAdmissionError, ClientSessionError) as exc:
        return ApiResponse(409, {"status": "conflict", "reason": str(exc)[:256]})
    return ApiResponse(
        200,
        {
            "mounted_snapshot_digest": admission.mounted_snapshot_digest,
            "ui_revision": snapshot.ui_revision,
        },
    )


def bind_client_run(
    app: ZebraAgentApi,
    task_id: str,
    run_id: str,
    body: dict[str, Any],
    auth: ClientAuthContext,
) -> ApiResponse:
    platform = app.client_platform
    if (
        platform is None
        or platform.client_sessions is None
        or platform.client_control_leases is None
    ):
        return ApiResponse(
            503, {"status": "unavailable", "reason": "client_integration_disabled"}
        )
    scope = tuple(str(item) for item in body.get("task_capability_scope") or ())
    try:
        binding, lease = ClientBindingService(
            platform.client_sessions, platform.client_control_leases
        ).bind_run(
            task_id=TaskId(_uuid(task_id)),
            run_id=run_id,
            session_id=auth.client_session_id,
            task_capability_scope=scope,
            controller=bool(body.get("controller", True)),
        )
    except (ClientAdmissionError, ClientSessionError) as exc:
        return ApiResponse(409, {"status": "conflict", "reason": str(exc)[:256]})
    return ApiResponse(
        201,
        {
            "binding_id": str(binding.binding_id),
            "binding_revision": binding.binding_revision,
            "binding_digest": binding.binding_digest,
            "allowed_actions": list(binding.allowed_actions),
            "controller": lease is not None,
        },
    )


def _uuid(value: str) -> UUID:
    return UUID(value)
