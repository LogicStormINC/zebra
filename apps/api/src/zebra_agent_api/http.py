from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest

HTTP_METHODS = ["DELETE", "GET", "PATCH", "POST", "PUT"]


def create_http_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
) -> FastAPI:
    adapter = RouteAdapter(create_app(database_path, settings=settings))
    app = FastAPI(title="Zebra Agent API")

    async def handle(request: Request, full_path: str = "") -> Response:
        del full_path
        response = adapter.handle(
            RouteRequest(
                method=request.method,
                path=request.url.path,
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
