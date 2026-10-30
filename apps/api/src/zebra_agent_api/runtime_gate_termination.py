"""Bounded management gates; machine auth only, no Worker-attestation ingress."""

import asyncio
import hashlib
import hmac
import re
from typing import Any
from uuid import UUID

import psycopg
from agent_core.application.runtime_gate_termination import RuntimeGateTerminationService
from agent_core.domain.runtime_gate_termination import CONTRACT_DIGEST
from agent_core.domain.runtime_gates import GateConflict
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementExpired,
    HostManagementUnavailable,
)
from agent_storage.postgres.runtime_gate_termination import RuntimeGateTerminationStore
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.runtime_gate_termination_config import load_runtime_gate_termination_approval
from zebra_agent_api.runtime_management import _HEADERS, _error

PATH = "/management/v1/runtime-gate-terminations"
CONTRACT = "runtime-gate-termination/1"


def perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    raw: bytes,
    method: str,
) -> dict[str, Any] | JSONResponse:
    try:
        approval = load_runtime_gate_termination_approval(
            settings.runtime_gate_termination_config, namespace
        )
    except (OSError, ValueError, TypeError):
        raise RuntimeError("GATE_CONFIGURATION_UNAVAILABLE") from None
    if not hmac.compare_digest(
        hashlib.sha256(token.encode()).hexdigest(), approval.credential_sha256
    ):
        return _error(401, "UNAUTHENTICATED")
    expected = {
        "deploymentId": approval.scope.deployment_id,
        "audience": approval.audience,
        "productId": approval.scope.product_id,
        "environment": approval.scope.environment,
        "trustRevision": str(approval.trust_revision),
    }
    if any(headers[h] != [str(expected[f])] for f, h in _HEADERS.items()):
        return _error(403, "SCOPE_MISMATCH")
    if headers["X-Runtime-Gate-Termination-Contract"] != [CONTRACT_DIGEST]:
        return _error(409, "CONTRACT_MISMATCH")
    store = RuntimeGateTerminationStore(settings.database_url, approval.scope, approval.trust)

    def recheck() -> None:
        if (
            load_runtime_gate_termination_approval(
                settings.runtime_gate_termination_config, namespace
            )
            != approval
        ):
            raise PermissionError("PERMISSION_DENIED")

    if method == "POST":
        if "terminate" not in approval.actions:
            return _error(403, "PERMISSION_DENIED")
        result = RuntimeGateTerminationService(store).terminate(raw, recheck)
    else:
        if "read" not in approval.actions:
            return _error(403, "PERMISSION_DENIED")
        operation = headers["X-Runtime-Operation"]
        if len(operation) > 1 or operation and str(UUID(operation[0])) != operation[0]:
            raise ValueError("INVALID_OPERATION")
        result = RuntimeGateTerminationService(store).read(operation[0] if operation else "")
    recheck()
    return {
        "contractVersion": CONTRACT,
        "contractDigest": CONTRACT_DIGEST,
        "scope": approval.scope.model_dump(mode="json"),
        "trustRevision": approval.trust_revision,
        **result,
    }


def register_runtime_gate_termination(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    slots = asyncio.Semaphore(4)

    async def handle(request: Request) -> JSONResponse:
        if request.method not in {"GET", "POST"}:
            response = _error(405, "METHOD_NOT_ALLOWED")
            response.headers["Allow"] = "GET, POST"
            return response
        if settings.runtime_gate_termination_config is None:
            return _error(503, "GATE_UNAVAILABLE")
        if request.url.query:
            return _error(400, "INVALID_ARGUMENT")
        values = request.headers.getlist("authorization")
        if len(values) != 1:
            return _error(401, "UNAUTHENTICATED")
        scheme, _, token = values[0].partition(" ")
        if scheme.lower() != "bearer" or re.fullmatch(r"rtgstop_[A-Za-z0-9_-]{43}", token) is None:
            return _error(401, "UNAUTHENTICATED")
        if slots.locked():
            return _error(429, "RATE_LIMITED")
        await slots.acquire()

        async def body() -> bytes:
            raw = b""
            async for chunk in request.stream():
                raw += chunk
                if len(raw) > 65536:
                    raise ValueError("INVALID_ARGUMENT")
            return raw

        try:
            raw = await asyncio.wait_for(body(), 0.5)
            if request.method == "GET" and raw:
                raise ValueError("INVALID_ARGUMENT")
            headers = {
                name: request.headers.getlist(name)
                for name in (
                    *_HEADERS.values(),
                    "X-Runtime-Operation",
                    "X-Runtime-Gate-Termination-Contract",
                )
            }
            if request.method == "POST" and (
                headers["X-Runtime-Operation"]
                or request.headers.get("content-type", "").split(";")[0] != "application/json"
            ):
                raise ValueError("INVALID_ARGUMENT")
        except (TimeoutError, ValueError):
            slots.release()
            return _error(400, "INVALID_ARGUMENT")
        except BaseException:
            slots.release()
            raise
        task = asyncio.create_task(
            asyncio.to_thread(perform, settings, namespace, token, headers, raw, request.method)
        )

        def finished(done: asyncio.Task[Any]) -> None:
            slots.release()
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        try:
            result = await asyncio.wait_for(asyncio.shield(task), 6)
            return (
                result
                if isinstance(result, JSONResponse)
                else JSONResponse(result, headers={"Cache-Control": "no-store"})
            )
        except (
            HostManagementConflict,
            GateConflict,
            psycopg.errors.SerializationFailure,
            psycopg.errors.DeadlockDetected,
        ):
            return _error(409, "REVISION_CONFLICT")
        except HostManagementExpired:
            return _error(401, "UNAUTHENTICATED")
        except (HostManagementUnavailable, PermissionError):
            return _error(403, "PERMISSION_DENIED")
        except LookupError:
            return _error(404, "NOT_FOUND")
        except OverflowError:
            return _error(429, "CAPACITY_EXCEEDED")
        except ValueError:
            return _error(400, "INVALID_ARGUMENT")
        except (TimeoutError, RuntimeError, OSError, psycopg.Error):
            return _error(503, "GATE_UNAVAILABLE")

    app.add_api_route(
        PATH,
        handle,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        response_model=None,
    )
