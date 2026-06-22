from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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

    async def handle(request: Request, full_path: str = "") -> JSONResponse:
        del full_path
        response = adapter.handle(
            RouteRequest(
                method=request.method,
                path=request.url.path,
            )
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    app.add_api_route("/", handle, methods=HTTP_METHODS)
    app.add_api_route("/{full_path:path}", handle, methods=HTTP_METHODS)
    return app
