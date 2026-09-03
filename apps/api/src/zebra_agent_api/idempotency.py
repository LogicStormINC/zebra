from __future__ import annotations

import hashlib
import json

from agent_core.ports import IdempotencyStorePort
from agent_storage import new_idempotency_record

from zebra_agent_api.responses import ApiResponse


def request_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scoped_idempotency_key(idempotency_key: str | None, host_context: object | None) -> str | None:
    """Partition Host admission receipts by the durable caller authority."""

    if idempotency_key is None or host_context is None:
        return idempotency_key
    principal_refs = sorted(
        str(getattr(resource, "resource_id", ""))
        for resource in getattr(host_context, "resource_refs", ())
        if getattr(resource, "resource_type", "") == "principal"
    )
    authority = {
        "host_app_id": str(getattr(host_context, "host_app_id", "")),
        "namespace_id": str(getattr(host_context, "namespace_id", "")),
        "principals": principal_refs,
        "workspace_ref": str(getattr(host_context, "workspace_ref", "")),
    }
    encoded = json.dumps(
        {"authority": authority, "idempotency_key": idempotency_key},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"host:{hashlib.sha256(encoded).hexdigest()}"


def replay_idempotent_response(
    *,
    store: IdempotencyStorePort,
    action: str,
    idempotency_key: str | None,
    payload: dict[str, object],
) -> ApiResponse | None:
    if idempotency_key is None:
        return None
    existing = store.get(
        action=action,
        idempotency_key=idempotency_key,
    )
    if existing is None:
        return None
    if existing.request_hash != request_hash(payload):
        return ApiResponse(
            status_code=409,
            body={
                "status": "idempotency_conflict",
                "reason": "idempotency key reused with different request",
            },
        )
    return ApiResponse(status_code=existing.status_code, body=existing.response_body)


def save_idempotent_response(
    *,
    store: IdempotencyStorePort,
    action: str,
    idempotency_key: str | None,
    payload: dict[str, object],
    response: ApiResponse,
    public_idempotency_key: str | None = None,
) -> ApiResponse:
    if idempotency_key is None:
        response.body["idempotency_key"] = None
        return response
    response.body["idempotency_key"] = public_idempotency_key or idempotency_key
    store.save(
        new_idempotency_record(
            action=action,
            idempotency_key=idempotency_key,
            request_hash=request_hash(payload),
            status_code=response.status_code,
            response_body=response.body,
        )
    )
    return response
