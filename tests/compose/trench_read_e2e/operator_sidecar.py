"""Acceptance-only operator sidecar for the Trench read-only E2E runner.

Endpoints (see docs/EMB-TRN-READ-E2E-01.md):

- ``GET /business-snapshot`` — deterministic ``trench.business-snapshot.v1``
  view (count + digest per configured Trench business table). Read-only.
- ``POST /worker-restart`` — protected hook that restarts the Zebra worker
  container through the Docker Engine API over the local unix socket. Only
  ``taskId``/``runId`` are accepted, never browser credentials.

This service exists only in the isolated acceptance environment; it is not
part of any product surface.
"""

from __future__ import annotations

import hashlib
import os
from typing import Annotated, Any

import httpx
import psycopg
from fastapi import FastAPI, Header, Response
from pydantic import BaseModel, ConfigDict

SNAPSHOT_SCHEMA = "trench.business-snapshot.v1"
DEFAULT_TABLES = "events,event_threads,states"


def _env_tables() -> tuple[str, ...]:
    raw = os.environ.get("TRENCH_SNAPSHOT_TABLES", DEFAULT_TABLES)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _snapshot_dsn() -> str:
    value = os.environ.get("TRENCH_SNAPSHOT_DATABASE_DSN", "").strip()
    if not value:
        raise RuntimeError("TRENCH_SNAPSHOT_DATABASE_DSN is required")
    return value


def collect_table_facts(dsn: str, tables: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    with psycopg.connect(dsn, autocommit=True) as connection:
        for table in tables:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT * FROM "{table}" ORDER BY 1')  # noqa: S608 - fixed table list
                rows = cursor.fetchall()
            digest = hashlib.sha256()
            for row in rows:
                digest.update(repr(row).encode())
                digest.update(b"\x1f")
            facts[table] = {"count": len(rows), "digest": digest.hexdigest()}
    return facts


class RestartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taskId: str
    runId: str


def _restart_worker(container: str) -> int:
    socket_path = os.environ.get("E2E_DOCKER_SOCKET", "/var/run/docker.sock")
    with httpx.Client(
        transport=httpx.HTTPTransport(uds=socket_path), timeout=30
    ) as client:
        response = client.post(f"http://docker/containers/{container}/restart?t=0")
    if response.status_code not in {200, 204}:
        raise RuntimeError(f"docker_restart_failed:{response.status_code}")
    return response.status_code


def create_sidecar() -> FastAPI:
    app = FastAPI(title="Trench E2E Operator Sidecar", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/business-snapshot")
    async def business_snapshot(response: Response) -> dict[str, Any]:
        try:
            tables = collect_table_facts(_snapshot_dsn(), _env_tables())
        except psycopg.Error as exc:
            response.status_code = 502
            return {"status": "error", "reason": f"snapshot_read_failed:{exc.__class__.__name__}"}
        except RuntimeError as exc:
            response.status_code = 500
            return {"status": "error", "reason": str(exc)}
        return {"schema_version": SNAPSHOT_SCHEMA, "tables": tables}

    @app.post("/worker-restart")
    async def worker_restart(
        body: RestartBody,
        response: Response,
        x_e2e_operator_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        expected = os.environ.get("E2E_OPERATOR_TOKEN", "")
        if not expected or x_e2e_operator_token != expected:
            response.status_code = 403
            return {"status": "rejected", "reason": "operator_token_invalid"}
        container = os.environ.get("E2E_WORKER_CONTAINER", "").strip()
        if not container:
            response.status_code = 500
            return {"status": "error", "reason": "worker_container_unconfigured"}
        del body  # taskId/runId are accepted for audit shape only
        try:
            _restart_worker(container)
        except (httpx.HTTPError, RuntimeError) as exc:
            response.status_code = 502
            return {"status": "error", "reason": str(exc)}
        return {"status": "restarted"}

    return app
