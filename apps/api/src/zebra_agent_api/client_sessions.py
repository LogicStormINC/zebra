"""Client session runtime routes (open / heartbeat / mount)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from agent_control_plane.client_admission import (
    ClientAdmissionError,
    ClientAdmissionService,
    ClientBindingService,
)
from agent_core.domain.client_capabilities import (
    CAPABILITY_NAME_PATTERN,
    MountedCapabilitySnapshot,
    ProfileLifecycle,
)
from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLease,
    ClientFenceError,
    ClientSessionError,
    ClientSessionGrant,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import ClientSessionId, TaskId

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.client_grant_auth import ClientAuthContext
from zebra_agent_api.responses import ApiResponse


def open_client_session(
    app: ZebraAgentApi,
    body: dict[str, Any],
    host_context: HostContextEnvelope | None = None,
) -> ApiResponse:
    if app.settings.deployment == "cloud" and host_context is None:
        return ApiResponse(
            401,
            {"status": "unauthorized", "reason": "verified_host_context_required"},
        )
    platform = app.client_platform
    if platform is None or platform.client_sessions is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    if platform.frontend_capabilities is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    try:
        grant = ClientSessionGrant.model_validate(body.get("grant") or {})
    except ValueError as exc:
        return ApiResponse(400, {"status": "invalid", "reason": str(exc)[:256]})
    if host_context is not None:
        try:
            grant.ensure_matches(
                host_app_id=host_context.host_app_id,
                namespace_id=host_context.namespace_id,
                frontend_app_id=grant.frontend_app_id,
                origin=host_context.origin,
            )
        except ClientSessionError as exc:
            return ApiResponse(403, {"status": "forbidden", "reason": str(exc)[:256]})
        binding = platform.frontend_capabilities.get_binding_for_host(
            host_context.host_app_id,
            host_context.namespace_id,
            grant.frontend_app_id,
        )
        if binding is None or binding.profile_digest != grant.profile_digest:
            return ApiResponse(
                403,
                {"status": "forbidden", "reason": "frontend_profile_not_bound"},
            )
    profile = platform.frontend_capabilities.get_profile_by_digest(
        grant.frontend_app_id, grant.profile_digest
    )
    if (
        profile is None
        or profile.profile_digest != grant.profile_digest
        or profile.lifecycle is not ProfileLifecycle.PUBLISHED
    ):
        return ApiResponse(409, {"status": "conflict", "reason": "grant_profile_not_active"})
    try:
        admission = ClientAdmissionService(platform.client_sessions).open_session(grant)
    except ClientAdmissionError as exc:
        return ApiResponse(409, {"status": "conflict", "reason": str(exc)[:256]})
    session = admission.session
    return ApiResponse(
        201,
        {
            "client_session_id": str(session.session_id),
            "status": session.status.value,
            "expires_at": session.expires_at.isoformat(),
            "session_credential": (f"{session.session_id}:{admission.credential.token}"),
        },
    )


def heartbeat_client_session(
    app: ZebraAgentApi,
    session_id: str,
    auth: ClientAuthContext,
    body: dict[str, Any],
    fence_token: str,
) -> ApiResponse:
    platform = app.client_platform
    if platform is None or platform.client_sessions is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    if auth.client_session_id != ClientSessionId(_uuid(session_id)):
        return ApiResponse(403, {"status": "forbidden", "reason": "session_authority_mismatch"})
    try:
        session = ClientAdmissionService(platform.client_sessions).heartbeat(
            ClientSessionId(_uuid(session_id))
        )
    except ClientSessionError:
        return ApiResponse(409, {"status": "expired", "reason": "client_session_expired"})
    lease_expiry: str | None = None
    if body:
        lease = _controller_lease(app, auth, body)
        if lease is None or not fence_token:
            return ApiResponse(409, {"status": "rejected", "reason": "stale_client_fence"})
        assert platform.client_control_leases is not None
        try:
            renewed = platform.client_control_leases.renew(
                lease.run_binding_id,
                task_id=TaskId(_uuid(str(body["task_id"]))),
                run_id=str(body["run_id"]),
                fence=ClientControlFence(token=fence_token),
                ttl=timedelta(minutes=5),
            )
        except (ClientFenceError, ValueError, KeyError):
            return ApiResponse(409, {"status": "rejected", "reason": "stale_client_fence"})
        lease_expiry = renewed.expires_at.isoformat()
    return ApiResponse(
        200,
        {"status": session.status.value, "controller_expires_at": lease_expiry},
    )


def release_client_controller(
    app: ZebraAgentApi,
    auth: ClientAuthContext,
    body: dict[str, Any],
    fence_token: str,
) -> ApiResponse:
    platform = app.client_platform
    if platform is None or platform.client_control_leases is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    lease = _controller_lease(app, auth, body)
    if lease is None or not fence_token:
        return ApiResponse(409, {"status": "rejected", "reason": "stale_client_fence"})
    try:
        platform.client_control_leases.release(
            lease.run_binding_id,
            task_id=TaskId(_uuid(str(body["task_id"]))),
            run_id=str(body["run_id"]),
            fence=ClientControlFence(token=fence_token),
        )
    except (ClientFenceError, ValueError, KeyError):
        return ApiResponse(409, {"status": "rejected", "reason": "stale_client_fence"})
    return ApiResponse(200, {"status": "released"})


def mount_client_session(
    app: ZebraAgentApi, session_id: str, body: dict[str, Any], auth: ClientAuthContext
) -> ApiResponse:
    platform = app.client_platform
    if platform is None or platform.client_sessions is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    try:
        snapshot = MountedCapabilitySnapshot.model_validate(body)
    except ValueError as exc:
        return ApiResponse(400, {"status": "invalid", "reason": str(exc)[:256]})
    if auth.client_session_id != ClientSessionId(_uuid(session_id)):
        return ApiResponse(403, {"status": "forbidden", "reason": "session_authority_mismatch"})
    if snapshot.client_session_id != ClientSessionId(_uuid(session_id)):
        return ApiResponse(409, {"status": "conflict", "reason": "session_id_mismatch"})
    if platform.frontend_capabilities is None:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    profile = platform.frontend_capabilities.get_profile(
        snapshot.frontend_app_id, snapshot.profile_revision
    )
    if profile is None:
        return ApiResponse(409, {"status": "conflict", "reason": "profile_not_found"})
    try:
        admission = ClientAdmissionService(platform.client_sessions).mount(
            ClientSessionId(_uuid(session_id)), snapshot, profile=profile
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
    host_context: HostContextEnvelope | None = None,
) -> ApiResponse:
    platform = app.client_platform
    if (
        platform is None
        or platform.client_sessions is None
        or platform.client_control_leases is None
    ):
        return ApiResponse(503, {"status": "unavailable", "reason": "client_integration_disabled"})
    raw_scope = body.get("task_capability_scope", ())
    controller = body.get("controller", True)
    if (
        not isinstance(raw_scope, list | tuple)
        or len(raw_scope) > 128
        or any(
            not isinstance(item, str) or CAPABILITY_NAME_PATTERN.fullmatch(item) is None
            for item in raw_scope
        )
    ):
        return ApiResponse(400, {"status": "invalid", "reason": "invalid_task_scope"})
    if not isinstance(controller, bool):
        return ApiResponse(400, {"status": "invalid", "reason": "invalid_controller_role"})
    if not run_id or len(run_id) > 128:
        return ApiResponse(400, {"status": "invalid", "reason": "invalid_run_id"})
    scope = tuple(raw_scope)
    try:
        parsed_task_id = TaskId(_uuid(task_id))
    except ValueError:
        return ApiResponse(400, {"status": "invalid", "reason": "invalid_task_id"})
    if app.settings.deployment == "cloud":
        task = app.stores.tasks.get_task(parsed_task_id)
        if task is None:
            return ApiResponse(404, {"status": "not_found", "reason": "unknown_task"})
        if host_context is None or task.namespace != host_context.namespace_id:
            return ApiResponse(
                403,
                {"status": "forbidden", "reason": "task_namespace_mismatch"},
            )
    try:
        admission = ClientBindingService(
            platform.client_sessions, platform.client_control_leases
        ).bind_run(
            task_id=parsed_task_id,
            run_id=run_id,
            session_id=auth.client_session_id,
            task_capability_scope=scope,
            controller=controller,
        )
    except (ClientAdmissionError, ClientSessionError) as exc:
        return ApiResponse(409, {"status": "conflict", "reason": str(exc)[:256]})
    binding, lease = admission.binding, admission.lease
    return ApiResponse(
        201,
        {
            "binding_id": str(binding.binding_id),
            "binding_revision": binding.binding_revision,
            "binding_digest": binding.binding_digest,
            "allowed_actions": list(binding.allowed_actions),
            "controller": lease is not None,
            "controller_fence_token": (
                admission.controller_fence.token if admission.controller_fence is not None else None
            ),
        },
    )


def _uuid(value: str) -> UUID:
    return UUID(value)


def _controller_lease(
    app: ZebraAgentApi,
    auth: ClientAuthContext,
    body: dict[str, Any],
) -> ClientControlLease | None:
    platform = app.client_platform
    if platform is None or platform.client_control_leases is None:
        return None
    try:
        lease = platform.client_control_leases.get_active(UUID(str(body["run_binding_id"])))
    except (ValueError, KeyError):
        return None
    if lease is None or lease.client_session_id != auth.client_session_id:
        return None
    return lease
