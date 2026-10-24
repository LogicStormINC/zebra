"""One dispatch per original admission. Immutable sealed receipts; observation never retries."""

import base64
import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Literal
from uuid import UUID, uuid4

from agent_core.domain.client_capabilities import ProfileLifecycle
from agent_storage import PostgresControlPlaneStores, new_idempotency_record
from agent_storage.idempotency import IdempotencyConflictError
from agent_storage.postgres.task_io import task_io_deadline
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field

from zebra_agent_api.client_grant_auth import SessionBackedClientGrantAuthorizer
from zebra_agent_api.client_surface import mount_client_surface, open_client_surface
from zebra_agent_api.idempotency import scoped_idempotency_key
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_api import create_task
from zebra_agent_api.tenant_guard import host_list_context_response, task_access_response

_PREFIX = "/v1/admission-operations/"
_CLAIM = "client-admission-v1-claim"
_RESULT = "client-admission-v1-result"


class Admission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["task_create", "surface_open", "surface_mount"]
    task: str = Field(max_length=36, default="")
    run: str = Field(max_length=128, default="")
    payload: dict[str, Any]


def _header(request: Any, name: str) -> str:
    return next((v for k, v in (request.headers or {}).items() if k.lower() == name.lower()), "")


def _authorize(app: Any, request: Any, meta: dict[str, Any]) -> ApiResponse | None:
    context = request.host_context
    if context is None:
        return ApiResponse(401, {"status": "unauthorized"})
    denied = host_list_context_response(context, request.verified_host_grant)
    if denied is not None:
        return denied
    if meta["kind"] != "task_create":
        denied = task_access_response(
            app,
            meta["task"],
            context,
            verified_host_grant=request.verified_host_grant,
            run_id=meta["run"],
        )
        if denied is not None:
            return denied
    if meta["kind"] != "task_create":
        platform = app.client_platform
        if platform is None or platform.frontend_capabilities is None:
            return ApiResponse(503, {"status": "unavailable"})
        app_id, digest = meta.get("frontend_app"), meta.get("profile")
        binding = platform.frontend_capabilities.get_binding_for_host(
            context.host_app_id,
            context.namespace_id,
            app_id,
        )
        profile = platform.frontend_capabilities.get_profile_by_digest(app_id, digest)
        if (
            binding is None
            or binding.profile_digest != digest
            or profile is None
            or profile.lifecycle is not ProfileLifecycle.PUBLISHED
        ):
            return ApiResponse(403, {"status": "profile_not_current"})
    if meta["kind"] == "surface_mount":
        platform = app.client_platform
        if platform is None or platform.client_sessions is None:
            return ApiResponse(503, {"status": "unavailable"})
        auth = SessionBackedClientGrantAuthorizer(platform.client_sessions).authorize(
            request.headers,
            host_context=context,
            require_host_context=True,
            verified_host_grant=request.verified_host_grant,
        )
        if auth is None:
            return ApiResponse(401, {"status": "unauthorized"})
    return None


def _dispatch(app: Any, request: Any, body: Admission, operation: str) -> ApiResponse:
    if body.kind == "task_create":
        return create_task(
            app,
            body.payload,
            idempotency_key="admission-v1:" + operation,
            host_context=request.host_context,
            verified_host_grant=request.verified_host_grant,
        )
    inner = replace(
        request,
        path=f"/v1/tasks/{body.task}/runs/{body.run}/client-surface",
        body=body.payload,
    )
    if body.kind == "surface_open":
        return open_client_surface(app, inner)
    auth = SessionBackedClientGrantAuthorizer(app.client_platform.client_sessions).authorize(
        request.headers,
        host_context=request.host_context,
        require_host_context=True,
        verified_host_grant=request.verified_host_grant,
    )
    if auth is None:
        return ApiResponse(401, {"status": "unauthorized"})
    return mount_client_surface(app, inner, auth)


def handle_admission_operation(app: Any, request: Any) -> ApiResponse | None:
    if not request.path.startswith(_PREFIX):
        return None
    observation = request.path.endswith("/observation")
    termination = (
        request.path.endswith("/termination")
        or request.path.endswith("/atomic-termination")
        or request.path.endswith("/task-termination")
    )
    if observation and request.method.upper() != "GET":
        return ApiResponse(405, {"status": "method_not_allowed"})
    if termination and request.body is not None:
        return ApiResponse(400, {"status": "invalid_termination"})
    if request.query or request.method.upper() == "GET" and request.body is not None:
        return ApiResponse(400, {"status": "invalid_admission_observation"})
    if request.method.upper() not in {"GET", "POST"}:
        return ApiResponse(405, {"status": "method_not_allowed"})
    if not isinstance(app.stores, PostgresControlPlaneStores):
        return ApiResponse(503, {"status": "admission_operations_unavailable"})
    try:
        operation = str(
            UUID(
                request.path.removeprefix(_PREFIX)
                .removesuffix("/observation")
                .removesuffix("/termination")
                .removesuffix("/atomic-termination")
                .removesuffix("/task-termination")
            )
        )
        if observation or termination:
            digest = _header(request, "X-Zebra-Admission-Hash")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("invalid original hash")
        raw_key = _header(request, "X-Zebra-Admission-Key")
        key = bytes.fromhex(raw_key)
        if len(key) != 32 or len(raw_key) != 64:
            raise ValueError("invalid recovery key")
        if len(json.dumps(request.body or {}).encode()) > 65536:
            raise ValueError("admission too large")
    except ValueError:
        return ApiResponse(400, {"status": "invalid_admission_operation"})
    context = request.host_context
    if context is None:
        return ApiResponse(401, {"status": "unauthorized"})
    verified = request.verified_host_grant
    denied = host_list_context_response(context, verified)
    if denied is not None:
        return denied
    scoped = scoped_idempotency_key(operation, context)
    scoped = _request_hash(
        {
            "key": scoped,
            "issuer": verified.authority_issuer,
            "subject": verified.subject_ref,
            "origin": context.origin,
            "resources": sorted(ref.key for ref in context.resource_refs),
        }
    )
    assert scoped is not None
    try:
        with task_io_deadline(monotonic() + 2):
            return _handle(
                app,
                request,
                operation,
                scoped,
                key,
                observation=observation,
                termination=termination,
            )
    except IdempotencyConflictError:
        return ApiResponse(409, {"status": "admission_operation_conflict"})
    except TimeoutError:
        return ApiResponse(503, {"status": "unknown", "operation": operation})


def _handle(
    app: Any,
    request: Any,
    operation: str,
    scoped: str,
    key: bytes,
    *,
    observation: bool = False,
    termination: bool = False,
) -> ApiResponse:
    store = app.stores.idempotency
    claim = store.get(action=_CLAIM, idempotency_key=scoped)
    body = None
    digest = _header(request, "X-Zebra-Admission-Hash")
    credential_hash = hashlib.sha256(
        _header(request, "X-Zebra-Client-Session").encode()
    ).hexdigest()
    key_hash = hashlib.sha256(key).hexdigest()
    if request.method.upper() == "POST" and not termination:
        try:
            protocol = _header(request, "X-Zebra-Admission-Protocol")
            if protocol not in {"", "pre-dispatch/1", "atomic-surface/1", "atomic-task/1"}:
                raise ValueError("unsupported dispatch protocol")
            body = Admission.model_validate(request.body or {})
            if protocol == "atomic-surface/1":
                from zebra_agent_api.client_admission_atomic import eligible_atomic_surface

                if body.kind == "task_create" or not eligible_atomic_surface(app):
                    raise ValueError("atomic surface requires exact same PG ports")
            if protocol == "atomic-task/1":
                from zebra_agent_api.client_admission_task import validate_atomic_task

                validate_atomic_task(app, body)
            _bounded_numbers(body.payload)
            if body.kind == "task_create":
                if body.task or body.run or body.payload.get("execute") is not False:
                    raise ValueError("only explicit non-executing creation is supported")
            elif not body.run or any(ord(c) < 33 for c in body.run):
                raise ValueError("invalid run")
            else:
                UUID(body.task)
            digest = _request_hash(
                {
                    **body.model_dump(),
                    "key_hash": key_hash,
                    "credential_hash": credential_hash,
                    **(
                        {"dispatch_protocol": protocol}
                        if protocol in {"atomic-surface/1", "atomic-task/1"}
                        else {}
                    ),
                }
            )
        except ValueError:
            return ApiResponse(400, {"status": "invalid_admission_operation"})
        mount = body.payload.get("mount", {})
        if not isinstance(mount, dict):
            return ApiResponse(400, {"status": "invalid_admission_operation"})
        meta = {
            "dispatch_protocol": protocol,
            "frontend_app": mount.get("frontend_app_id"),
            "profile": mount.get("profile_digest"),
            "kind": body.kind,
            "task": body.task,
            "run": body.run,
            "key_hash": key_hash,
            "credential_hash": credential_hash,
        }
    elif claim is None:
        denied = host_list_context_response(request.host_context, request.verified_host_grant)
        if termination:
            from zebra_agent_api.client_admission_termination import termination_response

            return denied or termination_response(
                operation,
                digest,
                "",
                {"state": "not_observed", "recorded_at": ""},
                version=3
                if request.path.endswith("/task-termination")
                else (2 if request.path.endswith("/atomic-termination") else 1),
            )
        return denied or (
            _observation(operation, digest, None, None)
            if observation
            else ApiResponse(200, {"status": "not_observed", "operation": operation})
        )
    else:
        meta = claim.response_body
    denied = _authorize(app, request, meta)
    if denied is not None:
        return denied
    if claim is not None and (
        claim.request_hash != digest
        or claim.response_body["key_hash"] != key_hash
        or claim.response_body["credential_hash"] != credential_hash
    ):
        return ApiResponse(409, {"status": "admission_operation_conflict"})
    if termination:
        from zebra_agent_api.client_admission_termination import terminate_admission

        return terminate_admission(app, request, operation, scoped, digest, meta)
    if observation:
        result = store.get(action=_RESULT, idempotency_key=scoped)
        denied = _authorize(app, request, meta)
        if denied is not None:
            return denied
        if result is not None and result.request_hash != digest:
            return ApiResponse(503, {"status": "observation_unavailable"})
        return _observation(operation, digest, meta, result)
    if claim is None:
        assert body is not None
        nonce = str(uuid4())
        claim = store.save(
            new_idempotency_record(
                action=_CLAIM,
                idempotency_key=scoped,
                request_hash=digest,
                status_code=202,
                response_body={**meta, "claim": nonce},
            )
        )
        if claim.response_body["claim"] == nonce:
            if meta.get("dispatch_protocol") == "pre-dispatch/1":
                fence = store.admission_fence(scoped, digest, terminate=False)
                if fence["state"] != "started":
                    return ApiResponse(
                        200, {"status": "unknown", "operation": operation, "request_hash": digest}
                    )
            if meta.get("dispatch_protocol") in {"atomic-surface/1", "atomic-task/1"}:
                from zebra_agent_api.client_admission_atomic import execute_atomic_surface

                execute_atomic_surface(app, request, body, scoped, key, digest, operation)
            else:
                # Legacy partial commits and their original receipts remain unchanged.
                response = _dispatch(app, request, body, scoped)
                if not _persist_result(store, response, operation, scoped, key, digest):
                    return ApiResponse(503, {"status": "unknown", "operation": operation})
    result = store.get(action=_RESULT, idempotency_key=scoped)
    denied = _authorize(app, request, meta)
    if denied is not None:
        return denied
    return ApiResponse(
        200,
        result.response_body
        if result
        else {
            "status": "unknown",
            "operation": operation,
            "request_hash": digest,
        },
    )


def _persist_result(
    store: Any, response: ApiResponse, operation: str, scoped: str, key: bytes, digest: str
) -> bool:
    raw = json.dumps(response.body, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 131072:
        return False
    iv = os.urandom(12)
    sealed = base64.b64encode(iv + AESGCM(key).encrypt(iv, raw, digest.encode())).decode()
    store.save(
        new_idempotency_record(
            action=_RESULT,
            idempotency_key=scoped,
            request_hash=digest,
            status_code=200,
            response_body={
                "status": "completed",
                "operation": operation,
                "request_hash": digest,
                "response_status": response.status_code,
                "sealed_response": sealed,
            },
        )
    )
    return True


def _request_hash(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _bounded_numbers(value: Any) -> None:
    if isinstance(value, float) or isinstance(value, int) and abs(value) > 9007199254740991:
        raise ValueError("only bounded integers are supported")
    if isinstance(value, dict):
        for child in value.values():
            _bounded_numbers(child)
    elif isinstance(value, list):
        for child in value:
            _bounded_numbers(child)


def _observation(operation: str, digest: str, claim: Any, result: Any) -> ApiResponse:
    # Original immutable facts only. A missing result cannot prove that dispatch
    # stopped or that no native effect committed; never inspect/repair Controller.
    return ApiResponse(
        200,
        {
            "contract_version": 1,
            "operation": operation,
            "request_hash": digest,
            "kind": claim["kind"] if claim else "",
            "claim_recorded": claim is not None,
            "result_recorded": result is not None,
            "partial_commit_possible": claim is not None and result is None,
            "retry_allowed": False,
            "controller_reclaim_allowed": False,
            "observed_at": datetime.now(UTC).isoformat(),
        },
    )
