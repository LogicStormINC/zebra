from __future__ import annotations

import json
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
from zebra_agent_api.routes import RouteAdapter, RouteRequest

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
    adapter = RouteAdapter(
        create_app(
            database_path,
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
        response = adapter.handle(
            RouteRequest(
                method=request.method,
                path=request.url.path,
                body=body,
                headers=dict(request.headers),
                query=dict(request.query_params),
            )
        )
        if _is_stream_request(request) and response.status_code == 200:
            return StreamingResponse(
                _encode_sse_events(response.body["events"]),
                media_type="text/event-stream",
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


def _encode_sse_events(events: object) -> list[str]:
    chunks: list[str] = []
    for event in _coerce_events(events):
        chunks.append(
            f"id: {event['event_id']}\n"
            "event: session_event\n"
            f"data: {json.dumps(event, sort_keys=True)}\n\n"
        )
    return chunks


def _coerce_events(events: object) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        raise TypeError("stream response must include a list of events")
    normalized: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            raise TypeError("stream event must be a mapping")
        normalized.append(dict(event))
    return normalized


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
