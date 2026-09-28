from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_core.domain.user_personalization import normalize_user_instructions
from agent_core.ports.user_personalization import UserPersonalizationConflictError

from zebra_agent_api.responses import ApiResponse, bad_request, service_unavailable


def get_user_personalization(*, stores: object, user_id: str) -> ApiResponse:
    store = _store(stores)
    if store is None:
        return _unavailable()
    try:
        record = store.get(_identity(user_id))
    except ValueError as exc:
        return bad_request(str(exc))
    if record is None:
        return ApiResponse(
            status_code=200,
            body={"instructions": "", "revision": 0, "updated_at": None},
        )
    return ApiResponse(status_code=200, body=_body(record))


def update_user_personalization(
    *, stores: object, user_id: str, payload: dict[str, object]
) -> ApiResponse:
    store = _store(stores)
    if store is None:
        return _unavailable()
    try:
        record = store.put(
            _identity(user_id),
            normalize_user_instructions(_string(payload, "instructions")),
            expected_revision=_revision(payload, allow_zero=True),
            operator=_identity(_string(payload, "operator")),
        )
    except ValueError as exc:
        return bad_request(str(exc))
    except UserPersonalizationConflictError as exc:
        return ApiResponse(
            status_code=409,
            body={"status": "revision_conflict", "reason": str(exc)},
        )
    return ApiResponse(status_code=200, body=_body(record))


def clear_user_personalization(
    *, stores: object, user_id: str, payload: dict[str, object]
) -> ApiResponse:
    store = _store(stores)
    if store is None:
        return _unavailable()
    try:
        record = store.clear(
            _identity(user_id),
            expected_revision=_revision(payload, allow_zero=False),
            operator=_identity(_string(payload, "operator")),
        )
    except ValueError as exc:
        return bad_request(str(exc))
    except UserPersonalizationConflictError as exc:
        return ApiResponse(
            status_code=409,
            body={"status": "revision_conflict", "reason": str(exc)},
        )
    return ApiResponse(status_code=200, body=_body(record))


def _store(stores: object) -> Any | None:
    return getattr(stores, "personalization", None)


def _body(record: Any) -> dict[str, object]:
    updated_at: datetime = record.updated_at
    return {
        "instructions": record.instructions or "",
        "revision": record.revision,
        "updated_at": updated_at.isoformat(),
    }


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _revision(payload: dict[str, object], *, allow_zero: bool) -> int:
    value = payload.get("expected_revision")
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"expected_revision must be an integer >= {minimum}")
    return value


def _identity(value: str) -> str:
    if not value or value != value.strip() or len(value) > 255:
        raise ValueError("identity must be non-blank, trimmed, and at most 255 characters")
    return value


def _unavailable() -> ApiResponse:
    return service_unavailable(
        status="personalization_unavailable",
        reason="user personalization requires the cloud control plane",
    )
