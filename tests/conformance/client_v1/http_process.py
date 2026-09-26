"""Minimal real HTTP process around production client runtime routes."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from agent_storage import sqlite_control_plane_stores
from agent_storage.postgres_platform_composition import postgres_agent_platform_control_plane
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.settings import ApiSettings, ModelSettings


def create_process_app() -> FastAPI:
    dsn = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    namespace = os.environ["ZEBRA_TEST_NAMESPACE"]
    local_database = Path(os.environ["ZEBRA_TEST_LOCAL_DB"])
    settings = ZebraAgentSettings(
        profile="test",
        database_url=str(local_database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )
    api = ZebraAgentApi(
        database_path=local_database,
        settings=settings,
        _stores=sqlite_control_plane_stores(local_database),
        client_platform=postgres_agent_platform_control_plane(
            dsn,
            deployment_namespace=namespace,
            client_integration_enabled=True,
        ),
    )
    adapter = RouteAdapter(api)
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/{path:path}", methods=["GET", "POST", "OPTIONS"])
    async def dispatch(request: Request, path: str) -> JSONResponse:
        if request.method == "OPTIONS":
            return JSONResponse({"status": "ok"})
        if (
            os.environ.get("ZEBRA_TEST_REJECT_RECEIPTS") == "1"
            and request.method == "POST"
            and request.url.path.endswith("/receipts")
        ):
            return JSONResponse(
                {"status": "unavailable", "reason": "injected_disconnect"},
                status_code=503,
            )
        body = await request.json() if request.method == "POST" else None
        response = adapter.handle(
            RouteRequest(
                method=request.method,
                path=f"/{path}",
                body=body,
                headers=dict(request.headers),
            )
        )
        return JSONResponse(response.body, status_code=response.status_code)

    return app


if __name__ == "__main__":
    uvicorn.run(
        create_process_app(),
        host="127.0.0.1",
        port=int(os.environ.get("ZEBRA_TEST_API_PORT", "18082")),
        log_level="warning",
    )
