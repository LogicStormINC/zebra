from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_storage import SQLiteIdempotencyStore, new_idempotency_record

from zebra_agent_api.responses import ApiResponse


def request_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def replay_idempotent_response(
    *,
    database_path: Path,
    action: str,
    idempotency_key: str | None,
    payload: dict[str, object],
) -> ApiResponse | None:
    if idempotency_key is None:
        return None
    existing = SQLiteIdempotencyStore(database_path).get(
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
    database_path: Path,
    action: str,
    idempotency_key: str | None,
    payload: dict[str, object],
    response: ApiResponse,
) -> ApiResponse:
    if idempotency_key is None:
        response.body["idempotency_key"] = None
        return response
    response.body["idempotency_key"] = idempotency_key
    SQLiteIdempotencyStore(database_path).save(
        new_idempotency_record(
            action=action,
            idempotency_key=idempotency_key,
            request_hash=request_hash(payload),
            status_code=response.status_code,
            response_body=response.body,
        )
    )
    return response
