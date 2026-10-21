"""Bounded scoped Host administration; execution/connector authority is unchanged."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID

import psycopg
from agent_storage import CloudCompositionSettings
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementExpired,
    HostManagementStore,
    HostManagementUnavailable,
)
from agent_storage.postgres.task_io import task_io_deadline
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.extension_request_body import _unique_object
from zebra_agent_api.host_registry_config import load_host_management_config, registry_wire
from zebra_agent_api.runtime_management import _HEADERS, _error, register_runtime_management

CONTRACT = "host-registry-management/1"
PATH = "/management/v1/host-registry"
REQUEST_TIMEOUT = 5.0


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    method: str,
    body: dict[str, Any] | None,
) -> JSONResponse:
    config = load_host_management_config(settings.host_management_config, namespace)
    if not hmac.compare_digest(
        hashlib.sha256(token.encode()).hexdigest(), config.credential_sha256
    ):
        return _error(401, "UNAUTHENTICATED")
    for field, header in _HEADERS.items():
        expected = str(config.trust.revision) if field == "trustRevision" else config.scope[field]
        if headers[header] != [expected]:
            return _error(403, "SCOPE_MISMATCH")
    action = "host-registry.read" if method == "GET" else "host-registry.write"
    if action not in config.actions or config.trust.expires_at <= datetime.now(UTC):
        return _error(403, "PERMISSION_DENIED")
    if namespace is None or not settings.database_url.startswith(("postgres://", "postgresql://")):
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    store = HostManagementStore(settings.database_url, deployment_namespace=namespace)
    try:
        if body is None:
            result = store.read(config.trust)
        else:
            record = replace(config.registry, active=body["active"])
            result = store.apply(
                config.trust, record, body["expectedRevision"], body["operationId"]
            )
    except HostManagementConflict:
        return _error(409, "CONFLICT")
    except HostManagementExpired:
        return _error(403, "PERMISSION_DENIED")
    except HostManagementUnavailable:
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    return JSONResponse(
        content={
            "contractVersion": CONTRACT,
            "registry": registry_wire(result.record),
            "revision": result.revision,
            "replayed": result.replayed,
        },
        headers={"Cache-Control": "no-store"},
    )


async def _body(request: Request) -> dict[str, Any] | None:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            raise ValueError("body too large")
    if request.method == "GET":
        if raw:
            raise ValueError("GET body forbidden")
        return None
    if request.headers.getlist("content-type") != ["application/json"]:
        raise ValueError("JSON body required")
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or set(value) != {"expectedRevision", "operationId", "active"}:
        raise ValueError("invalid request fields")
    if (
        type(value["expectedRevision"]) is not int
        or not 0 <= value["expectedRevision"] <= 2**53 - 2
    ):
        raise ValueError("invalid revision")
    if type(value["active"]) is not bool or not isinstance(value["operationId"], str):
        raise ValueError("invalid active or operation")
    if str(UUID(value["operationId"])) != value["operationId"]:
        raise ValueError("canonical operation UUID required")
    return value


def register_host_registry_management(
    app: FastAPI,
    settings: ZebraAgentSettings,
    namespace: str | None,
) -> None:
    slots = asyncio.Semaphore(8)

    async def handle(request: Request) -> JSONResponse:
        if request.method not in {"GET", "PUT"}:
            response = _error(405, "METHOD_NOT_ALLOWED")
            response.headers["Allow"] = "GET, PUT"
            return response
        tokens = request.headers.getlist("authorization")
        if len(tokens) != 1:
            return _error(401, "UNAUTHENTICATED")
        scheme, _, token = tokens[0].partition(" ")
        if scheme.lower() != "bearer" or re.fullmatch(r"rthm_[A-Za-z0-9_-]{43}", token) is None:
            return _error(401, "UNAUTHENTICATED")
        if request.url.query or request.headers.getlist("cookie"):
            return _error(400, "INVALID_ARGUMENT")
        if slots.locked():
            response = _error(429, "RATE_LIMITED")
            response.headers["Retry-After"] = "1"
            return response
        await slots.acquire()
        try:
            body = await asyncio.wait_for(_body(request), 0.2)
        except (ValueError, TypeError, RecursionError, TimeoutError):
            slots.release()
            return _error(400, "INVALID_ARGUMENT")
        except BaseException:
            slots.release()
            raise
        headers = {header: request.headers.getlist(header) for header in _HEADERS.values()}
        with task_io_deadline(monotonic() + REQUEST_TIMEOUT):
            task = asyncio.create_task(
                asyncio.to_thread(
                    _perform, settings, namespace, token, headers, request.method, body
                )
            )

        def finished(done: asyncio.Task[JSONResponse]) -> None:
            slots.release()
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(task), REQUEST_TIMEOUT)
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            RecursionError,
            TimeoutError,
            psycopg.Error,
        ):
            return _error(503, "MANAGEMENT_UNAVAILABLE")

    app.add_api_route(
        PATH,
        handle,
        methods=["GET", "PUT", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        response_model=None,
    )


def register_management_routes(
    app: FastAPI,
    settings: ZebraAgentSettings,
    namespace: Callable[[], str | None],
    cloud_composition: CloudCompositionSettings | None = None,
) -> None:
    """Keep optional management composition lazy when both routes are disabled."""
    enabled = settings.runtime_management_config or settings.host_management_config
    current = namespace() if enabled else None
    register_runtime_management(app, settings, current)
    host_settings = (
        replace(settings, database_url=cloud_composition.dsn)
        if cloud_composition is not None
        else settings
    )
    register_host_registry_management(app, host_settings, current)
