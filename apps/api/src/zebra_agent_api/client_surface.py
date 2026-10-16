"""Compose existing client admission operations with fresh Host authority."""

from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, Annotated
from uuid import UUID, uuid4

from agent_core.domain.client_capabilities import CAPABILITY_NAME_PATTERN, MountedCapabilitySnapshot
from agent_core.domain.client_sessions import ClientSessionGrant
from agent_storage.postgres.task_io import task_io_deadline
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from zebra_agent_api.client_grant_auth import (
    ClientAuthContext,
    SessionBackedClientGrantAuthorizer,
)
from zebra_agent_api.client_sessions import (
    bind_client_run,
    mount_client_session,
    open_client_session,
)
from zebra_agent_api.responses import ApiResponse, bad_request
from zebra_agent_api.tenant_guard import host_list_context_response, task_access_response

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi
    from zebra_agent_api.routes import RouteRequest


class ClientSurfaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mount: MountedCapabilitySnapshot
    task_capability_scope: list[Annotated[str, Field(pattern=CAPABILITY_NAME_PATTERN)]] = Field(
        max_length=128
    )
    controller: StrictBool = True

    @field_validator("mount")
    @classmethod
    def bounded_mount(cls, value: MountedCapabilitySnapshot) -> MountedCapabilitySnapshot:
        for names in (value.mounted_actions, value.mounted_readables):
            if len(names) > 128 or any(CAPABILITY_NAME_PATTERN.fullmatch(n) is None for n in names):
                raise ValueError("mounted capabilities exceed the admission bound")
        return value


def client_surface_target(path: str) -> tuple[str, str]:
    parts = path.strip("/").split("/")
    if (
        len(parts) != 6
        or parts[:2] != ["v1", "tasks"]
        or parts[3] != "runs"
        or parts[5] != "client-surface"
        or not parts[4].strip()
        or len(parts[4]) > 128
        or any(ord(c) < 32 for c in parts[4])
    ):
        raise ValueError("invalid client surface target")
    return str(UUID(parts[2])), parts[4]


def mount_client_surface(
    app: "ZebraAgentApi", request: "RouteRequest", auth: ClientAuthContext
) -> ApiResponse:
    try:
        task_id, run_id = client_surface_target(request.path)
        body = ClientSurfaceRequest.model_validate(request.body or {})
    except ValueError:
        return bad_request("invalid_client_surface")
    if body.mount.client_session_id != auth.client_session_id:
        return ApiResponse(403, {"status": "forbidden", "reason": "session_authority_mismatch"})
    context = request.host_context
    if app.settings.deployment == "cloud":
        if context is None:
            return ApiResponse(401, {"status": "unauthorized"})
        denied = host_list_context_response(context, request.verified_host_grant)
        if denied is not None:
            return denied
    deadline = monotonic() + 2
    if context is not None and context.expires_at is not None:
        deadline = min(
            deadline, monotonic() + (context.expires_at - datetime.now(UTC)).total_seconds()
        )
    try:
        with task_io_deadline(deadline):
            denied = task_access_response(
                app,
                task_id,
                context,
                verified_host_grant=request.verified_host_grant,
                run_id=run_id,
            )
            if denied is not None:
                return denied
            return _mount_and_bind(app, request, body, auth, task_id, run_id)
    except TimeoutError:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_surface_deadline"})


def _mount_and_bind(
    app: "ZebraAgentApi",
    request: "RouteRequest",
    body: ClientSurfaceRequest,
    auth: ClientAuthContext,
    task_id: str,
    run_id: str,
) -> ApiResponse:
    """Internal continuation after the current request's target authority check."""
    mounted = mount_client_session(
        app, str(auth.client_session_id), body.mount.model_dump(mode="json"), auth
    )
    if mounted.status_code != 200:
        return mounted
    binding = bind_client_run(
        app,
        task_id,
        run_id,
        {
            "task_capability_scope": body.task_capability_scope,
            "controller": body.controller,
        },
        auth,
        request.host_context,
    )
    if binding.status_code != 201:
        return binding
    # ponytail: keep the original partial-commit/retry semantics. A retry
    # reuses the binding and rotates its fence; no bearer response is stored.
    return ApiResponse(201, {**mounted.body, **binding.body})


def open_client_surface(app: "ZebraAgentApi", request: "RouteRequest") -> ApiResponse:
    """Host/BFF-only composition; never cache or retry a credential-bearing result."""
    body = dict(request.body or {})
    try:
        task_id, run_id = client_surface_target(request.path)
        grant = ClientSessionGrant.model_validate(body.pop("grant"))
        mount = body.get("mount")
        if not isinstance(mount, dict) or "client_session_id" in mount:
            raise ValueError("new sessions require a server-issued identity")
        parsed = ClientSurfaceRequest.model_validate(
            {**body, "mount": {**mount, "client_session_id": str(uuid4())}}
        )
    except (KeyError, ValueError):
        return bad_request("invalid_client_surface_open")
    context = request.host_context
    if context is None:
        return ApiResponse(401, {"status": "unauthorized"})
    denied = host_list_context_response(context, request.verified_host_grant)
    if denied is not None:
        return denied
    deadline = monotonic() + 2
    if context.expires_at is not None:
        deadline = min(
            deadline, monotonic() + (context.expires_at - datetime.now(UTC)).total_seconds()
        )
    try:
        with task_io_deadline(deadline):
            denied = task_access_response(
                app,
                task_id,
                context,
                verified_host_grant=request.verified_host_grant,
                run_id=run_id,
            )
            if denied is not None:
                return denied
            opened = open_client_session(app, {"grant": grant.model_dump(mode="json")}, context)
            if opened.status_code != 201:
                return opened
            platform = app.client_platform
            assert platform is not None and platform.client_sessions is not None
            credential = opened.body["session_credential"]
            assert isinstance(credential, str)
            auth = SessionBackedClientGrantAuthorizer(platform.client_sessions).authorize(
                {"X-Zebra-Client-Session": credential},
                host_context=context,
                require_host_context=True,
            )
            if auth is None:
                return ApiResponse(401, {"status": "unauthorized"})
            mounted = parsed.model_copy(
                update={
                    "mount": parsed.mount.model_copy(
                        update={"client_session_id": auth.client_session_id}
                    )
                }
            )
            bound = _mount_and_bind(app, request, mounted, auth, task_id, run_id)
            if bound.status_code != 201:
                return bound
            # ponytail: existing operations may partially commit. Lost responses never
            # trigger automatic reopen/fallback; abandoned sessions expire at their TTL.
            return ApiResponse(201, {**opened.body, **bound.body})
    except TimeoutError:
        return ApiResponse(503, {"status": "unavailable", "reason": "client_surface_deadline"})
