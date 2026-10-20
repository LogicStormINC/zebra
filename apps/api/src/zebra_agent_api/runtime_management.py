"""Dedicated read-only management transport; no business or execution authority."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import stat
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from agent_storage.postgres.migrations import MIGRATIONS
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.extension_request_body import _unique_object

CONTRACT = "runtime-management/1"
TARGET_PATH = "/management/v1/target"
_FIELDS = {
    "deploymentId",
    "deploymentNamespace",
    "audience",
    "productId",
    "environment",
    "trustRevision",
    "credentialSha256",
    "expiresAt",
    "actions",
}
_HEADERS = {
    "deploymentId": "X-Runtime-Deployment",
    "audience": "X-Runtime-Audience",
    "productId": "X-Runtime-Product",
    "environment": "X-Runtime-Environment",
    "trustRevision": "X-Runtime-Trust-Revision",
}


def _config(path: str | None, namespace: str | None) -> dict[str, Any]:
    if path is None or not Path(path).is_absolute():
        raise ValueError("management configuration required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}:
            raise ValueError("private regular configuration required")
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("configuration too large")
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("invalid configuration fields")
    for field in ("deploymentId", "deploymentNamespace", "audience", "productId", "environment"):
        if (
            not isinstance(value[field], str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value[field]) is None
        ):
            raise ValueError("invalid identity")
    if namespace is None or value["deploymentNamespace"] != namespace:
        raise ValueError("deployment namespace mismatch")
    if type(value["trustRevision"]) is not int or not 1 <= value["trustRevision"] <= 2**53 - 1:
        raise ValueError("invalid trust revision")
    if value["actions"] != ["target.describe"]:
        raise ValueError("read-only action required")
    if (
        not isinstance(value["credentialSha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["credentialSha256"]) is None
    ):
        raise ValueError("invalid credential digest")
    if not isinstance(value["expiresAt"], str) or not value["expiresAt"].endswith("Z"):
        raise ValueError("UTC credential deadline required")
    value["expiresAt"] = datetime.fromisoformat(value["expiresAt"])
    return value


def _error(status: int, code: str) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = 'Bearer realm="runtime-management"'
    return JSONResponse(status_code=status, content={"error": {"code": code}}, headers=headers)


def register_runtime_management(
    app: FastAPI,
    settings: ZebraAgentSettings,
    namespace: str | None,
) -> None:
    # ponytail: this read-only descriptor performs no DB/Worker probe. Those remain
    # explicit not_checked until a separately tested readiness contract exists.
    slots = asyncio.Semaphore(8)

    async def describe(request: Request) -> JSONResponse:
        if request.method != "GET":
            response = _error(405, "METHOD_NOT_ALLOWED")
            response.headers["Allow"] = "GET"
            return response
        if (
            request.url.query
            or request.headers.get("content-length", "0") != "0"
            or request.headers.get("transfer-encoding")
        ):
            return _error(400, "INVALID_ARGUMENT")
        tokens = request.headers.getlist("authorization")
        if len(tokens) != 1:
            return _error(401, "UNAUTHENTICATED")
        scheme, _, token = tokens[0].partition(" ")
        if scheme.lower() != "bearer" or re.fullmatch(r"rtmg_[A-Za-z0-9_-]{43}", token) is None:
            return _error(401, "UNAUTHENTICATED")

        async def empty_body() -> bool:
            async for chunk in request.stream():
                if chunk:
                    return False
            return True

        try:
            if not await asyncio.wait_for(empty_body(), 0.2):
                return _error(400, "INVALID_ARGUMENT")
        except TimeoutError:
            return _error(400, "INVALID_ARGUMENT")
        if slots.locked():
            response = _error(429, "RATE_LIMITED")
            response.headers["Retry-After"] = "1"
            return response
        await slots.acquire()
        read = asyncio.create_task(
            asyncio.to_thread(_config, settings.runtime_management_config, namespace)
        )

        # Keep the capacity slot until the actual read ends, including timed-out callers.
        def release_read(task: asyncio.Task[dict[str, Any]]) -> None:
            slots.release()
            if not task.cancelled():
                task.exception()  # Retrieve late failures without exposing file paths or values.

        read.add_done_callback(release_read)
        try:
            config = await asyncio.wait_for(asyncio.shield(read), 1.0)
        except (OSError, ValueError, TypeError, OverflowError, TimeoutError):
            return _error(503, "MANAGEMENT_UNAVAILABLE")
        if not hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), config["credentialSha256"]
        ):
            return _error(401, "UNAUTHENTICATED")
        now = datetime.now(UTC)
        if config["expiresAt"] <= now:
            return _error(401, "UNAUTHENTICATED")
        for field, header in _HEADERS.items():
            values = request.headers.getlist(header)
            if len(values) != 1 or values[0] != str(config[field]):
                return _error(403, "SCOPE_MISMATCH")
        return JSONResponse(
            content={
                "contractVersion": CONTRACT,
                "deploymentId": config["deploymentId"],
                "deploymentNamespace": namespace,
                "audience": config["audience"],
                "productId": config["productId"],
                "environment": config["environment"],
                "trustRevision": config["trustRevision"],
                "observedAt": now.isoformat(),
                "engine": "cloud-agent",
                "apiPackageVersion": version("zebra-agent-api"),
                "codeMigrationVersion": MIGRATIONS[-1].version,
                "checks": {"database": "not_checked", "worker": "not_checked"},
                "capabilities": {
                    "bundleManagement": "unsupported",
                    "nativeScriptAbi": "unsupported",
                },
            },
            headers={"Cache-Control": "no-store"},
        )

    app.add_api_route(
        TARGET_PATH,
        describe,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        response_model=None,
    )
