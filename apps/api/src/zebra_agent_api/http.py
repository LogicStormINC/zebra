from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from agent_core.domain.host_authority import HostContextEnvelope
from agent_integrations import GitHubPullRequestTransport
from agent_security import CredentialBroker, HostGrantSecurityError
from agent_storage import CloudCompositionSettings, ControlPlaneStores, PostgresControlPlaneStores
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_api.ag_ui_stream import (
    AgUiStreamContext,
    prepare_agui_stream,
    tail_agui_events,
)
from zebra_agent_api.app import create_app
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_api.session_identity_read import _parse_session_id
from zebra_agent_api.session_streaming import tail_session_events, tail_task_events
from zebra_agent_api.task_api import parse_task_id

HTTP_METHODS = ["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"]
HTTP_ALLOWED_HEADERS = ["Accept", "Authorization", "Content-Type", "Last-Event-ID"]


@dataclass(frozen=True)
class HostGrantHttpRequest:
    """Transient request data passed to the injected Host Grant adapter."""

    method: str
    path: str
    origin: str | None
    authorization: str


class HostGrantRequestAuthorizer(Protocol):
    """JWT/registry/replay adapter owned by the production composition root."""

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        """Exact registry-backed origins used by the CORS composition."""
        ...

    def authorize(self, request: HostGrantHttpRequest) -> object | None:
        """Verify the bearer Grant, bindings, scope and replay state."""


def create_http_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
    stores: ControlPlaneStores | None = None,
    cloud_composition: CloudCompositionSettings | None = None,
    administrative_context_namespace: str | None = None,
    context_administrative_namespace: str | None = None,
    credential_broker: CredentialBroker | None = None,
    credential_env: Mapping[str, str] | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
    host_grant_authorizer: HostGrantRequestAuthorizer | None = None,
    host_grant_origins: tuple[str, ...] | None = None,
) -> FastAPI:
    active_settings = settings or load_settings()
    active_database_path = Path(database_path or active_settings.database_url)
    api = create_app(
        active_database_path,
        settings=active_settings,
        stores=stores,
        cloud_composition=cloud_composition,
        administrative_context_namespace=administrative_context_namespace,
        context_administrative_namespace=context_administrative_namespace,
        credential_broker=credential_broker,
        credential_env=credential_env,
        github_transport=github_transport,
    )
    active_host_grant_authorizer = host_grant_authorizer
    if active_host_grant_authorizer is None and active_settings.deployment != "local":
        active_host_grant_authorizer = _compose_production_host_grant_authorizer(
            active_settings,
            api.stores,
            cloud_composition=cloud_composition,
        )
    adapter = RouteAdapter(api)
    exact_host_origins = _resolve_host_origins(
        active_host_grant_authorizer,
        host_grant_origins,
    )
    app = FastAPI(title="Zebra Agent API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if active_settings.deployment == "local" else exact_host_origins,
        allow_methods=HTTP_METHODS,
        allow_headers=HTTP_ALLOWED_HEADERS,
        allow_credentials=False,
    )

    async def handle(request: Request, full_path: str = "") -> Response:
        del full_path
        if request.method.upper() == "OPTIONS":
            return Response(status_code=200)
        auth_error = _authorize_request(
            request,
            active_settings,
            host_grant_authorizer=active_host_grant_authorizer,
            host_grant_origins=exact_host_origins,
        )
        if auth_error is not None:
            return auth_error
        body, body_error = await _read_request_body(request)
        if body_error is not None:
            return body_error
        if _is_agui_stream_request(request):
            from zebra_agent_api.tenant_guard import (
                session_tenant_denied,
                tenant_forbidden_response,
            )

            agui_thread = _stream_resource_id(request.url.path).split("/")[0]
            if session_tenant_denied(
                api.stores.sessions,
                agui_thread,
                getattr(request.state, "host_context", None),
            ):
                denied = tenant_forbidden_response(agui_thread)
                return JSONResponse(status_code=denied.status_code, content=denied.body)
            agui_stream = prepare_agui_stream(
                api.stores,
                request.url.path,
                request.query_params,
            )
            if isinstance(agui_stream, ApiResponse):
                return JSONResponse(status_code=agui_stream.status_code, content=agui_stream.body)
            if isinstance(agui_stream, AgUiStreamContext):
                return StreamingResponse(
                    tail_agui_events(agui_stream, request),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                )
        route_request = RouteRequest(
            method=request.method,
            path=request.url.path,
            body=body,
            headers=dict(request.headers),
            query=dict(request.query_params),
            host_context=getattr(request.state, "host_context", None),
        )
        response = await asyncio.to_thread(adapter.handle, route_request)
        if _is_stream_request(request) and response.status_code == 200:
            stream_id = _stream_resource_id(request.url.path)
            after_sequence, cursor_error = _after_sequence(request)
            if cursor_error is not None:
                return cursor_error
            if request.url.path.startswith("/tasks/"):
                task_key = parse_task_id(stream_id)
                if isinstance(task_key, ApiResponse):
                    return JSONResponse(
                        status_code=task_key.status_code,
                        content=task_key.body,
                    )
                stream = tail_task_events(
                    database_path=active_database_path,
                    stores=api.stores,
                    task_id=task_key,
                    request=request,
                    after_sequence=after_sequence,
                )
            else:
                session_key = _parse_session_id(stream_id)
                if isinstance(session_key, ApiResponse):
                    return JSONResponse(
                        status_code=session_key.status_code,
                        content=session_key.body,
                    )
                stream = tail_session_events(
                    database_path=active_database_path,
                    stores=api.stores,
                    live_event_fanout=api.live_event_fanout,
                    deployment_namespace=_deployment_namespace(api),
                    session_id=session_key,
                    request=request,
                    after_sequence=after_sequence,
                )
            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        return JSONResponse(status_code=response.status_code, content=response.body)

    app.add_api_route("/", handle, methods=HTTP_METHODS, response_model=None)
    app.add_api_route("/{full_path:path}", handle, methods=HTTP_METHODS, response_model=None)
    return app


def _compose_production_host_grant_authorizer(
    settings: ZebraAgentSettings,
    stores: ControlPlaneStores,
    *,
    cloud_composition: CloudCompositionSettings | None,
) -> HostGrantRequestAuthorizer | None:
    """Build the default cloud authorizer only for the PostgreSQL composition."""
    if not isinstance(stores, PostgresControlPlaneStores):
        return None
    from zebra_agent_api.host_auth import build_postgres_host_grant_authorizer

    return build_postgres_host_grant_authorizer(
        cloud_composition.dsn if cloud_composition is not None else settings.database_url,
        deployment_namespace=stores.deployment_namespace,
    )


def _is_stream_request(request: Request) -> bool:
    return request.method.upper() == "GET" and request.url.path.endswith("/stream")


def _is_agui_stream_request(request: Request) -> bool:
    parts = tuple(part for part in request.url.path.split("/") if part)
    return (
        request.method.upper() == "GET"
        and len(parts) == 6
        and parts[:2] == ("agui", "threads")
        and parts[3] == "runs"
        and parts[5] == "stream"
    )


async def _read_request_body(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    if request.method.upper() not in {"POST", "PUT", "PATCH"}:
        return None, None
    raw_body = await request.body()
    if not raw_body:
        return None, None
    try:
        payload = await request.json()
    except JSONDecodeError:
        return None, JSONResponse(
            status_code=400,
            content={
                "status": "invalid_request",
                "reason": "request body must be valid JSON",
            },
        )
    if not isinstance(payload, dict):
        return None, JSONResponse(
            status_code=400,
            content={
                "status": "invalid_request",
                "reason": "request body must be a JSON object",
            },
        )
    return dict(payload), None


def _stream_resource_id(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    return parts[-2] if len(parts) >= 2 else ""


def _deployment_namespace(api: object) -> str | None:
    stores = getattr(api, "stores", None)
    namespace = getattr(stores, "deployment_namespace", None)
    if isinstance(namespace, str) and namespace.strip():
        return namespace
    settings = getattr(api, "settings", None)
    return "local" if getattr(settings, "deployment", None) == "local" else None


def _after_sequence(request: Request) -> tuple[int, JSONResponse | None]:
    raw = request.query_params.get("after_sequence")
    if raw is None:
        return -1, None
    try:
        value = int(raw)
    except ValueError:
        value = -2
    if value < -1:
        return -1, JSONResponse(
            status_code=400,
            content={
                "status": "invalid_request",
                "reason": "after_sequence must be an integer greater than or equal to -1",
            },
        )
    return value, None


def _authorize_request(
    request: Request,
    settings: ZebraAgentSettings,
    *,
    host_grant_authorizer: HostGrantRequestAuthorizer | None,
    host_grant_origins: tuple[str, ...],
) -> JSONResponse | None:
    if request.method.upper() == "OPTIONS":
        return None
    if request.url.path == "/health":
        return None
    if settings.deployment != "local":
        return _authorize_host_request(
            request,
            host_grant_authorizer=host_grant_authorizer,
            host_grant_origins=host_grant_origins,
        )
    expected_token = settings.api.auth_token
    if expected_token is None:
        return None
    header = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        return _unauthorized()
    provided_token = header.removeprefix(prefix).strip()
    if provided_token != expected_token:
        return _unauthorized()
    return None


def _authorize_host_request(
    request: Request,
    *,
    host_grant_authorizer: HostGrantRequestAuthorizer | None,
    host_grant_origins: tuple[str, ...],
) -> JSONResponse | None:
    origin = request.headers.get("origin")
    if origin is not None:
        try:
            normalized_origin = _normalize_exact_origin(origin)
        except ValueError:
            return _forbidden("host_origin_not_allowed")
        if normalized_origin not in host_grant_origins:
            return _forbidden("host_origin_not_allowed")
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or not authorization.removeprefix("Bearer ").strip():
        return _unauthorized(reason="missing_or_invalid_host_grant")
    if host_grant_authorizer is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "reason": "host_grant_authorizer_unconfigured",
            },
        )
    try:
        verified = host_grant_authorizer.authorize(
            HostGrantHttpRequest(
                method=request.method.upper(),
                path=request.url.path,
                origin=origin,
                authorization=authorization,
            )
        )
        context = getattr(verified, "context", None)
        if context is not None and not isinstance(context, HostContextEnvelope):
            return _forbidden("host_grant_context_invalid")
        request.state.host_context = context
    except (HostGrantSecurityError, ValueError):
        return _forbidden("host_grant_rejected")
    return None


def _resolve_host_origins(
    authorizer: HostGrantRequestAuthorizer | None,
    configured_origins: tuple[str, ...] | None,
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


def _normalize_exact_origin(value: str) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Host Grant origins must be exact HTTPS origins")
    host = parsed.hostname
    if host is None:
        raise ValueError("Host Grant origin must contain a host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Host Grant origin has an invalid port") from exc
    return f"https://{host.lower()}{f':{port}' if port is not None else ''}"


def _unauthorized(*, reason: str = "missing_or_invalid_bearer_token") -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "status": "unauthorized",
            "reason": reason,
        },
    )


def _forbidden(reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "status": "forbidden",
            "reason": reason,
        },
    )
