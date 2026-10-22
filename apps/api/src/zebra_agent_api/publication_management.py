"""Bounded machine publisher HTTP channel, separate from business Task admission."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

import psycopg
from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_storage import CloudCompositionSettings
from agent_storage.postgres.agent_registry import PostgresAgentRegistry
from agent_storage.postgres.host_management import HostManagementConflict, HostManagementUnavailable
from agent_storage.postgres.publication import PublicationStore
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.routing import Route
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.publication_config import load_publication_approval
from zebra_agent_api.publication_service import mutate_publication
from zebra_agent_api.runtime_management import _HEADERS, _error
from zebra_agent_api.script_publication_contract import (
    CONTRACT as SCRIPT_CONTRACT,
)
from zebra_agent_api.script_publication_contract import (
    HEADER as SCRIPT_HEADER,
)
from zebra_agent_api.script_publication_contract import (
    PATH as SCRIPT_PATH,
)
from zebra_agent_api.script_publication_contract import (
    script_publication_contract,
)

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi

PATH = "/management/v1/runtime-publication"
CONTRACT = "runtime-publication/1"


def perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    method: str,
    raw: bytes,
    *,
    scripts: bool = False,
) -> JSONResponse:
    try:
        approval = load_publication_approval(settings.publication_management_config, namespace)
    except (OSError, ValueError, TypeError):
        raise RuntimeError("PUBLICATION_CONFIGURATION_UNAVAILABLE") from None
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
    if any(headers[name] != [expected[field]] for field, name in _HEADERS.items()):
        return _error(403, "SCOPE_MISMATCH")
    if namespace is None:
        raise ValueError("NAMESPACE_REQUIRED")
    contract = script_publication_contract() if scripts else None
    if contract is not None and headers[SCRIPT_HEADER] != [contract["contractDigest"]]:
        return _error(409, "CONTRACT_MISMATCH")
    store = PublicationStore(settings.database_url, namespace)
    if method == "GET":
        operation = headers["x-runtime-operation"]
        if len(operation) != 1 or str(UUID(operation[0])) != operation[0] or raw:
            raise ValueError("INVALID_ARGUMENT")
        if "read" not in approval.actions:
            return _error(403, "PERMISSION_DENIED")
        result = store.read(approval.trust, operation[0])
        if result is None:
            return _error(404, "NOT_FOUND")
    else:
        payload = load_bundle_json(raw)
        if not isinstance(payload, dict) or payload.get("action") not in approval.actions:
            return _error(403, "PERMISSION_DENIED")
        if (
            payload["action"] not in {"materialize", "publish"}
            or type(payload.get("expectedRevision")) is not int
            or not 0 <= payload["expectedRevision"] < 2**53 - 1
            or not isinstance(payload.get("operationId"), str)
            or not isinstance(payload.get("versionId"), str)
            or str(UUID(payload["operationId"])) != payload["operationId"]
            or str(UUID(payload["versionId"])) != payload["versionId"]
        ):
            raise ValueError("INVALID_ARGUMENT")
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        registry = PostgresAgentRegistry(settings.database_url, deployment_namespace=namespace)

        def recheck() -> None:
            if (
                load_publication_approval(settings.publication_management_config, namespace)
                != approval
            ):
                raise PermissionError("PERMISSION_DENIED")

        result = store.apply(
            approval.trust,
            payload["operationId"],
            digest,
            approval.definition_scope.scope_key,
            payload["expectedRevision"],
            lambda: mutate_publication(
                approval, payload, registry, settings.runtime_bundle_config, scripts=scripts
            ),
            recheck,
        )
    if (result.get("publicationContract") == SCRIPT_CONTRACT) != scripts:
        return _error(
            404 if method == "GET" else 409, "NOT_FOUND" if method == "GET" else "CONFLICT"
        )
    return JSONResponse(
        content={
            "contractVersion": SCRIPT_CONTRACT if scripts else CONTRACT,
            **({"contractDigest": contract["contractDigest"]} if contract is not None else {}),
            "scope": approval.scope.model_dump(mode="json"),
            "trustRevision": approval.trust_revision,
            "result": result,
        },
        headers={"Cache-Control": "no-store"},
    )


def register_publication_management(
    app: FastAPI,
    settings: ZebraAgentSettings,
    api: ZebraAgentApi,
    cloud_composition: CloudCompositionSettings | None = None,
) -> None:
    if cloud_composition is not None:
        settings = replace(settings, database_url=cloud_composition.dsn)
    slots = asyncio.Semaphore(4)

    async def handle(request: Request) -> JSONResponse:
        if request.method not in {"GET", "POST"}:
            return _error(405, "METHOD_NOT_ALLOWED")
        tokens = request.headers.getlist("authorization")
        token = tokens[0].removeprefix("Bearer ") if len(tokens) == 1 else ""
        if re.fullmatch(r"rtpub_[A-Za-z0-9_-]{43}", token) is None:
            return _error(401, "UNAUTHENTICATED")
        scripts = request.url.path.endswith(SCRIPT_PATH)
        names = (
            *_HEADERS.values(),
            "content-type",
            "content-length",
            "x-runtime-operation",
            SCRIPT_HEADER,
        )
        if (
            request.url.query
            or request.headers.getlist("cookie")
            or request.headers.getlist("content-encoding")
            or request.headers.getlist("transfer-encoding")
            or any(len(request.headers.getlist(n)) > 1 for n in names)
            or request.method == "POST"
            and request.headers.getlist("content-type") != ["application/json"]
        ):
            return _error(400, "INVALID_ARGUMENT")
        if slots.locked():
            return _error(429, "RATE_LIMITED")
        await slots.acquire()

        async def body() -> bytes:
            value = bytearray()
            async for chunk in request.stream():
                if len(value) + len(chunk) > 262144:
                    raise ValueError("BODY_TOO_LARGE")
                value.extend(chunk)
            return bytes(value)

        try:
            raw = await asyncio.wait_for(body(), 0.5)
        except (ValueError, TimeoutError):
            slots.release()
            return _error(400, "INVALID_ARGUMENT")
        except BaseException:
            slots.release()
            raise
        namespace = getattr(api.stores, "deployment_namespace", None)
        headers = {name: request.headers.getlist(name) for name in names}
        task = asyncio.create_task(
            asyncio.to_thread(
                perform, settings, namespace, token, headers, request.method, raw, scripts=scripts
            )
        )

        def finished(done: asyncio.Task[JSONResponse]) -> None:
            slots.release()
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(task), 6)
        except HostManagementConflict:
            return _error(409, "CONFLICT")
        except (HostManagementUnavailable, PermissionError):
            return _error(403, "PERMISSION_DENIED")
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            return _error(422, "PUBLICATION_REJECTED")
        except (OSError, psycopg.Error, TimeoutError, RuntimeError):
            return _error(503, "MANAGEMENT_UNAVAILABLE")

    # Both channels share the same per-instance resource budget and durable CAS.
    for path in (PATH, SCRIPT_PATH):
        route = Route(path, handle)
        route.methods = None
        app.router.routes.append(route)
