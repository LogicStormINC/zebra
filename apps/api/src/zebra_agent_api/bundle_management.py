"""Pure scoped Bundle validation; retained bounded threads, no execution effects."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from datetime import UTC, datetime
from typing import Any

from agent_core.domain.runtime_bundle import MAX_BUNDLE_BYTES, parse_runtime_bundle
from agent_core.domain.runtime_bundle_json import json_digest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect
from starlette.routing import Route
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.bundle_settings import load_execution_catalog

from zebra_agent_api.bundle_management_config import (
    BundleManagementApproval,
    load_bundle_management_approval,
)
from zebra_agent_api.bundle_management_contract import (
    CONTRACT,
    CONTRACT_PATH,
    VALIDATION_PATH,
    native_bundle_contract,
)
from zebra_agent_api.runtime_management import _HEADERS, _error

BODY_TIMEOUT = 0.2
REQUEST_TIMEOUT = 1.0


def _authorize(
    approval: BundleManagementApproval,
    token: str,
    headers: dict[str, list[str]],
    action: str,
) -> JSONResponse | None:
    if not hmac.compare_digest(
        hashlib.sha256(token.encode()).hexdigest(), approval.credential_sha256
    ):
        return _error(401, "UNAUTHENTICATED")
    scope = approval.scope
    expected = {
        "deploymentId": scope.deployment_id,
        "audience": approval.audience,
        "productId": scope.product_id,
        "environment": scope.environment,
        "trustRevision": str(approval.trust_revision),
    }
    if any(headers[header] != [expected[field]] for field, header in _HEADERS.items()):
        return _error(403, "SCOPE_MISMATCH")
    if action not in approval.actions or approval.deadline <= datetime.now(UTC):
        return _error(403, "PERMISSION_DENIED")
    return None


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    action: str,
    contract_header: str | None,
    raw: bytes,
) -> JSONResponse:
    initial = load_bundle_management_approval(settings.bundle_management_config, namespace)
    denied = _authorize(initial, token, headers, action)
    if denied is not None:
        return denied
    contract = native_bundle_contract()
    result: dict[str, Any] = {
        "contractVersion": CONTRACT,
        "contractDigest": contract["contractDigest"],
        "scope": initial.scope.model_dump(mode="json"),
        "trustRevision": initial.trust_revision,
    }
    if action == "bundle.contract.read":
        result["contract"] = contract
    else:
        if contract_header != contract["contractDigest"]:
            return _error(409, "CONTRACT_MISMATCH")
        try:
            bundle = parse_runtime_bundle(raw)
        except (ValueError, TypeError, OverflowError, RecursionError):
            return _error(422, "BUNDLE_REJECTED")
        if bundle.manifest.scope != initial.scope:
            return _error(403, "SCOPE_MISMATCH")
        catalog = load_execution_catalog(settings.runtime_bundle_config)
        if catalog.scope != initial.scope:
            return _error(403, "SCOPE_MISMATCH")
        try:
            assembly = catalog.resolve(bundle)
            result.update(
                bundleDigest=bundle.bundle_digest,
                assemblyDigest=assembly.assembly_digest,
                approvalDigest=json_digest(catalog.model_dump(mode="json")),
                checks={
                    "bundle": "passed",
                    "assetApproval": "passed",
                    "worker": "not_checked",
                    "publication": "not_performed",
                },
            )
        except (ValueError, TypeError, OverflowError, RecursionError):
            return _error(422, "BUNDLE_REJECTED")
    current = load_bundle_management_approval(settings.bundle_management_config, namespace)
    denied = _authorize(current, token, headers, action)
    if denied is not None:
        return denied
    if current != initial:
        return _error(403, "PERMISSION_DENIED")
    result["observedAt"] = datetime.now(UTC).isoformat()
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


async def _body(request: Request) -> bytes:
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BUNDLE_BYTES:
            raise ValueError("BODY_TOO_LARGE")
        raw.extend(chunk)
    if request.method == "GET" and raw:
        raise ValueError("GET_BODY_FORBIDDEN")
    length = request.headers.get("content-length")
    if length is not None and len(raw) != int(length):
        raise ValueError("BODY_LENGTH_MISMATCH")
    return bytes(raw)


def register_bundle_management(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    slots = asyncio.Semaphore(8)

    async def handle(request: Request) -> JSONResponse:
        method = "GET" if request.url.path == CONTRACT_PATH else "POST"
        if request.method != method:
            response = _error(405, "METHOD_NOT_ALLOWED")
            response.headers["Allow"] = method
            return response
        tokens = request.headers.getlist("authorization")
        if len(tokens) != 1:
            return _error(401, "UNAUTHENTICATED")
        scheme, _, token = tokens[0].partition(" ")
        if scheme.lower() != "bearer" or re.fullmatch(r"rtbv_[A-Za-z0-9_-]{43}", token) is None:
            return _error(401, "UNAUTHENTICATED")
        if (
            request.url.query
            or request.headers.getlist("cookie")
            or request.headers.getlist("content-encoding")
            or any(
                len(request.headers.getlist(name)) > 1
                for name in (
                    *_HEADERS.values(),
                    "content-type",
                    "content-length",
                    "transfer-encoding",
                    "x-runtime-bundle-contract",
                )
            )
        ):
            return _error(400, "INVALID_ARGUMENT")
        contract_headers = request.headers.getlist("x-runtime-bundle-contract")
        if method == "POST" and (
            request.headers.getlist("content-type") != ["application/json"]
            or len(contract_headers) != 1
        ):
            return _error(400, "INVALID_ARGUMENT")
        lengths = request.headers.getlist("content-length")
        if lengths and (
            re.fullmatch(r"[0-9]+", lengths[0]) is None
            or len(lengths[0]) > 7
            or int(lengths[0]) > (MAX_BUNDLE_BYTES if method == "POST" else 0)
        ):
            return _error(400, "INVALID_ARGUMENT")
        if request.headers.getlist("transfer-encoding") and (
            lengths
            or request.headers.getlist("transfer-encoding") != ["chunked"]
            or method == "GET"
        ):
            return _error(400, "INVALID_ARGUMENT")
        if slots.locked():
            response = _error(429, "RATE_LIMITED")
            response.headers["Retry-After"] = "1"
            return response
        await slots.acquire()
        try:
            raw = await asyncio.wait_for(_body(request), BODY_TIMEOUT)
        except (ValueError, TypeError, RecursionError, TimeoutError, ClientDisconnect):
            slots.release()
            return _error(400, "INVALID_ARGUMENT")
        except BaseException:
            slots.release()
            raise
        headers = {name: request.headers.getlist(name) for name in _HEADERS.values()}
        action = "bundle.contract.read" if method == "GET" else "bundle.validate"
        task = asyncio.create_task(
            asyncio.to_thread(
                _perform,
                settings,
                namespace,
                token,
                headers,
                action,
                contract_headers[0] if contract_headers else None,
                raw,
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
        ):
            return _error(503, "MANAGEMENT_UNAVAILABLE")

    for path in (CONTRACT_PATH, VALIDATION_PATH):
        route = Route(path, handle)
        route.methods = None  # Include extension methods in the scoped fixed-error handler.
        app.router.routes.append(route)
