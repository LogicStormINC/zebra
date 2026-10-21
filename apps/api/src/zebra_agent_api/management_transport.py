"""Shared bounded transport for the two actual Host administration endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import UUID

import psycopg
from agent_storage.postgres.task_io import task_io_deadline
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from zebra_agent_api.extension_request_body import _unique_object
from zebra_agent_api.host_registry_config import HostManagementConfig
from zebra_agent_api.runtime_management import _HEADERS, _error


def authorize_management(
    config: HostManagementConfig,
    token: str,
    headers: dict[str, list[str]],
    action: str,
) -> JSONResponse | None:
    if not hmac.compare_digest(
        hashlib.sha256(token.encode()).hexdigest(), config.credential_sha256
    ):
        return _error(401, "UNAUTHENTICATED")
    for field, header in _HEADERS.items():
        expected = str(config.trust.revision) if field == "trustRevision" else config.scope[field]
        if headers[header] != [expected]:
            return _error(403, "SCOPE_MISMATCH")
    if action not in config.actions or config.trust.expires_at <= datetime.now(UTC):
        return _error(403, "PERMISSION_DENIED")
    return None


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


def register_management_endpoint(
    app: FastAPI,
    path: str,
    perform: Callable[[str, dict[str, list[str]], str, dict[str, Any] | None], JSONResponse],
    *,
    timeout: float,
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
        with task_io_deadline(monotonic() + timeout):
            task = asyncio.create_task(
                asyncio.to_thread(perform, token, headers, request.method, body)
            )

        def finished(done: asyncio.Task[JSONResponse]) -> None:
            slots.release()
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout)
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
        path,
        handle,
        methods=["GET", "PUT", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        response_model=None,
    )
