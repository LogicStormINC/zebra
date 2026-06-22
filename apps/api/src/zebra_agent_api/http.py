from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest

HTTP_METHODS = ["DELETE", "GET", "PATCH", "POST", "PUT"]


def create_http_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
) -> FastAPI:
    active_settings = settings or load_settings()
    adapter = RouteAdapter(create_app(database_path, settings=active_settings))
    app = FastAPI(title="Zebra Agent API")

    async def handle(request: Request, full_path: str = "") -> Response:
        del full_path
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
