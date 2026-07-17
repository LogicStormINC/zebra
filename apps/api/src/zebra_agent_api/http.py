from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from agent_integrations import GitHubPullRequestTransport
from agent_security import CredentialBroker
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_api.app import create_app
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_api.session_identity_read import _parse_session_id
from zebra_agent_api.session_streaming import tail_session_events

HTTP_METHODS = ["DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"]


def create_http_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
    credential_broker: CredentialBroker | None = None,
    credential_env: Mapping[str, str] | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
) -> FastAPI:
    active_settings = settings or load_settings()
    active_database_path = Path(database_path or active_settings.database_url)
    adapter = RouteAdapter(
        create_app(
            active_database_path,
            settings=active_settings,
            credential_broker=credential_broker,
            credential_env=credential_env,
            github_transport=github_transport,
        )
    )
    app = FastAPI(title="Zebra Agent API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def _preflight_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method.upper() == "OPTIONS":
            origin = request.headers.get("origin", "*")
            requested_headers = request.headers.get("access-control-request-headers", "*")
            response = Response(status_code=204)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = ", ".join(HTTP_METHODS)
            response.headers["Access-Control-Allow-Headers"] = requested_headers
            response.headers["Access-Control-Max-Age"] = "600"
            return response
        return await call_next(request)

    async def handle(request: Request, full_path: str = "") -> Response:
        del full_path
        if request.method.upper() == "OPTIONS":
            return Response(status_code=200)
        auth_error = _authorize_request(request, active_settings)
        if auth_error is not None:
            return auth_error
        body, body_error = await _read_request_body(request)
        if body_error is not None:
            return body_error
        route_request = RouteRequest(
            method=request.method,
            path=request.url.path,
            body=body,
            headers=dict(request.headers),
            query=dict(request.query_params),
        )
        response = await asyncio.to_thread(adapter.handle, route_request)
        if _is_stream_request(request) and response.status_code == 200:
            session_key = _parse_session_id(_stream_session_id(request.url.path))
            if isinstance(session_key, ApiResponse):
                return JSONResponse(
                    status_code=session_key.status_code,
                    content=session_key.body,
                )
            after_sequence, cursor_error = _after_sequence(request)
            if cursor_error is not None:
                return cursor_error
            return StreamingResponse(
                tail_session_events(
                    database_path=active_database_path,
                    session_id=session_key,
                    request=request,
                    after_sequence=after_sequence,
                ),
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


def _is_stream_request(request: Request) -> bool:
    return request.method.upper() == "GET" and request.url.path.endswith("/stream")


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


def _stream_session_id(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    return parts[-2] if len(parts) >= 2 else ""


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


def _authorize_request(request: Request, settings: ZebraAgentSettings) -> JSONResponse | None:
    if request.method.upper() == "OPTIONS":
        return None
    if request.url.path == "/health":
        return None
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


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "status": "unauthorized",
            "reason": "missing_or_invalid_bearer_token",
        },
    )
