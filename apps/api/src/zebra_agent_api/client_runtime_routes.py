"""Runtime client route dispatcher (/v1/client-sessions, /v1/client-effects)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zebra_agent_api.routes import RouteRequest

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.client_effect_receipts import (
    get_client_effect,
    submit_client_effect_receipt,
)
from zebra_agent_api.client_grant_auth import (
    ClientAuthContext,
    SessionBackedClientGrantAuthorizer,
)
from zebra_agent_api.client_sessions import (
    bind_client_run,
    heartbeat_client_session,
    mount_client_session,
    open_client_session,
)
from zebra_agent_api.responses import ApiResponse, bad_request

_SESSION_PREFIX = "/v1/client-sessions"
_EFFECT_PREFIX = "/v1/client-effects"


def handle_client_runtime_route(
    app: ZebraAgentApi,
    request: RouteRequest,
) -> ApiResponse | None:
    path = request.path
    method = request.method.upper()
    if path == _SESSION_PREFIX and method == "POST":
        return open_client_session(app, request.body or {})
    if not (
        path.startswith(_SESSION_PREFIX)
        or path.startswith(_EFFECT_PREFIX)
        or path.endswith("/client-bindings")
    ):
        return None
    platform = app.client_platform
    if platform is None or platform.client_sessions is None:
        return ApiResponse(
            503, {"status": "unavailable", "reason": "client_integration_disabled"}
        )
    auth = SessionBackedClientGrantAuthorizer(platform.client_sessions).authorize(
        request.headers
    )
    if auth is None:
        return bad_request("client_session_authorization_required")
    if path.startswith(_SESSION_PREFIX):
        return _session_route(app, request, method, path, auth)
    if path.startswith(_EFFECT_PREFIX):
        return _effect_route(app, request, method, path, auth)
    return _binding_route(app, request, path, auth)


def _session_route(
    app: ZebraAgentApi,
    request: RouteRequest,
    method: str,
    path: str,
    auth: ClientAuthContext,
) -> ApiResponse:
    session_id = path.removeprefix(f"{_SESSION_PREFIX}/").split("/")[0]
    if not session_id:
        return bad_request("client_session_id_required")
    tail = path.removeprefix(f"{_SESSION_PREFIX}/{session_id}")
    if method == "POST" and tail == "/heartbeat":
        return heartbeat_client_session(app, session_id)
    if method == "POST" and tail == "/mount":
        return mount_client_session(
            app, session_id, request.body or {}, auth
        )
    return bad_request("unsupported client session operation")


def _effect_route(
    app: ZebraAgentApi,
    request: RouteRequest,
    method: str,
    path: str,
    auth: ClientAuthContext,
) -> ApiResponse:
    tail = path.removeprefix(_EFFECT_PREFIX)
    parts = [part for part in tail.split("/") if part]
    if len(parts) == 1 and method == "GET":
        return get_client_effect(app, parts[0])
    if len(parts) == 2 and parts[1] == "receipts" and method == "POST":
        idempotency_key = (request.headers or {}).get("Idempotency-Key") or ""
        if not idempotency_key.strip():
            return bad_request("missing_idempotency_key")
        return submit_client_effect_receipt(
            app,
            parts[0],
            request.body or {},
            fence_token=auth.fence_token,
            controller=auth.controller,
            idempotency_key=idempotency_key.strip(),
        )
    return bad_request("unsupported client effect operation")


def _binding_route(
    app: ZebraAgentApi,
    request: RouteRequest,
    path: str,
    auth: ClientAuthContext,
) -> ApiResponse:
    if request.method.upper() != "POST":
        return bad_request("unsupported client binding operation")
    parts = path.split("/")
    # /v1/tasks/{task_id}/runs/{run_id}/client-bindings
    try:
        task_id = parts[parts.index("tasks") + 1]
        run_id = parts[parts.index("runs") + 1]
    except (ValueError, IndexError):
        return bad_request("malformed client binding path")
    return bind_client_run(
        app, task_id, run_id, request.body or {}, auth
    )
