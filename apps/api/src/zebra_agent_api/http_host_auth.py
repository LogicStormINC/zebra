"""Bounded HTTP admission before a verified Host Grant is consumed."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, Any, Never, Protocol

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import require_task_host_context
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_security import HostGrantSecurityError
from agent_security.host_grant import VerifiedHostGrant
from agent_storage.postgres.host_auth import HostGrantConsumptionUnknown
from agent_storage.postgres.task_io import task_io_deadline
from fastapi import Request
from fastapi.responses import JSONResponse

from zebra_agent_api.ag_ui_command import (
    AgUiCommandEnvelope,
    _command_payload,
    _path_identity,
    _with_path_identity,
)
from zebra_agent_api.extension_reads import is_extension_path
from zebra_agent_api.extension_request_body import _unique_object
from zebra_agent_api.http_origins import _normalize_exact_origin
from zebra_agent_api.responses import ApiResponse, bad_request
from zebra_agent_api.session_binding import _build_binding_snapshot
from zebra_agent_api.session_identity_read import _parse_session_id
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.task_api import parse_task_id

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi

logger = logging.getLogger(__name__)
HOST_PREFLIGHT_SECONDS = 2.0
# Covers existing base64 image/document aggregate limits, including JSON overhead.
MAX_HOST_REQUEST_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class HostGrantHttpRequest:
    method: str
    path: str
    origin: str | None
    authorization: str
    deadline: float | None = None
    before_consume: Callable[[VerifiedHostGrant], None] | None = None


class HostGrantRequestAuthorizer(Protocol):
    @property
    def allowed_origins(self) -> tuple[str, ...]: ...

    def authorize(self, request: HostGrantHttpRequest) -> object | None: ...


class _TargetRejected(Exception):
    def __init__(self, response: ApiResponse) -> None:
        self.response = response
        super().__init__("Host target validation rejected")


def _reject(response: ApiResponse) -> Never:
    raise _TargetRejected(response)


def validate_host_target(
    api: ZebraAgentApi,
    path: str,
    method: str,
    body: dict[str, Any] | None,
    verified: VerifiedHostGrant,
) -> None:
    """Pure parsing and indexed authority reads, never adoption or renewal."""
    if path in {"/tasks", "/sessions"} and method == "POST":
        parsed = parse_create_session_payload(body or {})
        if isinstance(parsed, ApiResponse):
            _reject(parsed)
        _build_binding_snapshot(
            "prospective-admission",
            host_context=verified.context,
            verified_host_grant=verified,
            definition_snapshot_digest=None,
        )
        return

    task_id: TaskId | ApiResponse | None = None
    run_id: str | None = None
    parts = path.strip("/").split("/")
    if parts[0] == "agui":
        if method == "POST" and (identity := _path_identity(path)) is not None:
            try:
                payload = body or {}
                if isinstance(identity, tuple):
                    payload = _with_path_identity(payload, identity)
                envelope = AgUiCommandEnvelope.model_validate(payload)
                _command_payload(envelope)
            except (ValueError, TypeError):
                _reject(bad_request("invalid AG-UI command or target identity"))
            task_id, run_id = parse_task_id(envelope.thread_id), envelope.run_id
        elif len(parts) >= 5 and parts[:2] == ["agui", "threads"] and parts[3] == "runs":
            task_id, run_id = parse_task_id(parts[2]), parts[4]
        else:
            _reject(bad_request("invalid AG-UI resource target"))
    elif len(parts) >= 2 and parts[0] == "tasks":
        task_id = parse_task_id(parts[1])
    elif len(parts) >= 2 and parts[0] in {"sessions", "approvals"}:
        session_id = _parse_session_id(parts[1])
        if isinstance(session_id, ApiResponse):
            _reject(session_id)
        else:
            task_id = api.stores.tasks.task_id_for_session(session_id)
            if task_id is None:
                _reject(ApiResponse(404, {"status": "not_found"}))
    else:
        return
    if isinstance(task_id, ApiResponse):
        _reject(task_id)
    assert task_id is not None and not isinstance(task_id, ApiResponse)
    command = (body or {}).get("payload")
    if isinstance(command, dict):
        if "run_id" in command:
            candidate = command["run_id"]
            if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > 256:
                _reject(bad_request("invalid command Run target"))
            run_id = candidate
        if "thread_id" in command and command["thread_id"] != str(task_id):
            _reject(bad_request("command thread does not match its Task target"))
    control = api.cloud_control
    namespace = getattr(api.stores, "deployment_namespace", None)
    if control is None or not namespace or control.deployment_namespace != namespace:
        _reject(ApiResponse(503, {"status": "principal_binding_unavailable"}))
    assert control is not None
    binding = control.load_task_binding(task_id)
    if binding is None:
        _reject(ApiResponse(404, {"status": "not_found"}))
    assert binding is not None
    try:
        require_task_host_context(
            binding,
            verified.context,
            task_id=str(task_id),
            now=datetime.now(UTC),
            authority_issuer=verified.authority_issuer,
            run_id=run_id,
        )
    except ValueError:
        _reject(ApiResponse(404, {"status": "not_found"}))


async def authorize_request(
    request: Request,
    settings: object,
    *,
    api: ZebraAgentApi,
    host_grant_authorizer: HostGrantRequestAuthorizer | None,
    host_grant_origins: tuple[str, ...],
) -> JSONResponse | None:
    path = request.url.path
    if (
        request.method == "OPTIONS"
        and not is_extension_path(path)
        or path == "/health"
        or path.startswith("/platform/v1/frontend-profile")
    ):
        return None
    if getattr(settings, "deployment", None) == "local":
        expected = getattr(getattr(settings, "api", None), "auth_token", None)
        authorization = request.headers.get("authorization", "")
        if expected is None or (
            authorization.startswith("Bearer ")
            and authorization.removeprefix("Bearer ").strip() == expected
        ):
            return None
        return _unauthorized()
    error = _host_header_error(request, host_grant_authorizer, host_grant_origins)
    if error is not None:
        return error
    assert host_grant_authorizer is not None
    deadline = monotonic() + HOST_PREFLIGHT_SECONDS
    request.state.authorization_deadline = deadline
    body = None

    def operation() -> object | None:
        with task_io_deadline(deadline):
            return host_grant_authorizer.authorize(
                HostGrantHttpRequest(
                    method=request.method.upper(),
                    path=path,
                    origin=request.headers.get("origin"),
                    authorization=request.headers["authorization"],
                    deadline=deadline,
                    before_consume=lambda verified: validate_host_target(
                        api, path, request.method.upper(), body, verified
                    ),
                )
            )

    try:
        async with asyncio.timeout(max(0, deadline - monotonic())):
            if path in {"/tasks", "/sessions", "/agui/commands"} or path.startswith(
                ("/tasks/", "/sessions/", "/approvals/", "/agui/threads/")
            ):
                body, error = await _read_request_body(request, max_bytes=MAX_HOST_REQUEST_BYTES)
                if error is not None:
                    return error
                request.state.authorized_body = body
                request.state.authorized_body_read = True
            verified = await asyncio.to_thread(operation)
        context = getattr(verified, "context", None)
        if context is not None and not isinstance(context, HostContextEnvelope):
            return _forbidden("host_grant_context_invalid")
        if context is not None and (
            context.expires_at is None or datetime.now(UTC) >= context.expires_at
        ):
            return _forbidden("host_grant_rejected")
        if monotonic() >= deadline:
            raise TimeoutError("HTTP Host authorization deadline exceeded")
        request.state.host_context = context
        if isinstance(verified, VerifiedHostGrant):
            request.state.verified_host_grant = verified
    except _TargetRejected as exc:
        return JSONResponse(exc.response.body, status_code=exc.response.status_code)
    except CheckpointNotReady:
        return JSONResponse({"status": "projection_not_ready", "retryable": True}, status_code=409)
    except HostGrantConsumptionUnknown:
        return JSONResponse(
            {
                "status": "unavailable",
                "reason": "host_grant_consumption_unknown",
                "retryable": False,
            },
            status_code=503,
        )
    except (HostGrantSecurityError, ValueError) as exc:
        logger.warning("Host Grant request rejected: %s", type(exc).__name__)
        return _forbidden("host_grant_rejected")
    except Exception as exc:
        logger.warning("Host Grant authorization unavailable: %s", type(exc).__name__)
        # A timeout may happen after consumption began; never replay a command.
        return JSONResponse(
            {
                "status": "unavailable",
                "reason": "host_grant_authorization_unavailable",
                "retryable": False,
            },
            status_code=503,
        )
    return None


def _host_header_error(
    request: Request, authorizer: HostGrantRequestAuthorizer | None, origins: tuple[str, ...]
) -> JSONResponse | None:
    origin = request.headers.get("origin")
    if origin is not None:
        try:
            if _normalize_exact_origin(origin) not in origins:
                return _forbidden("host_origin_not_allowed")
        except ValueError:
            return _forbidden("host_origin_not_allowed")
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or not authorization.removeprefix("Bearer ").strip():
        return _unauthorized(reason="missing_or_invalid_host_grant")
    if authorizer is None:
        return JSONResponse(
            {"status": "unavailable", "reason": "host_grant_authorizer_unconfigured"},
            status_code=503,
        )
    return None


async def _read_request_body(
    request: Request, *, max_bytes: int | None = None
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    if request.method.upper() not in {"POST", "PUT", "PATCH"}:
        return None, None
    if max_bytes is None:
        raw_body = await request.body()
    else:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > max_bytes:
                return None, JSONResponse(
                    {"status": "invalid_request", "reason": "request_body_too_large"},
                    status_code=413,
                )
            body.extend(chunk)
        raw_body = bytes(body)
    if not raw_body:
        return None, None
    try:
        payload = await asyncio.to_thread(json.loads, raw_body, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None, JSONResponse(
            bad_request("request body must be valid JSON").body, status_code=400
        )
    if not isinstance(payload, dict):
        return None, JSONResponse(
            bad_request("request body must be a JSON object").body, status_code=400
        )
    return dict(payload), None


def _resolve_host_origins(
    authorizer: HostGrantRequestAuthorizer | None, configured_origins: tuple[str, ...] | None
) -> tuple[str, ...]:
    values = configured_origins
    if values is None and authorizer is not None:
        values = authorizer.allowed_origins
    if values is None:
        return ()
    normalized = tuple(_normalize_exact_origin(origin) for origin in values)
    if not normalized or len(set(normalized)) != len(normalized):
        raise ValueError("Host Grant origins must contain unique exact HTTPS origins")
    return normalized


def _unauthorized(*, reason: str = "missing_or_invalid_bearer_token") -> JSONResponse:
    return JSONResponse(status_code=401, content={"status": "unauthorized", "reason": reason})


def _forbidden(reason: str) -> JSONResponse:
    return JSONResponse(status_code=403, content={"status": "forbidden", "reason": reason})
