"""Validated payload primitives shared by durable event projection."""

import json
from collections.abc import Mapping

from agent_integrations.ag_ui.contracts import AgUiProjectionError


def required_payload_text(
    payload: Mapping[str, object], key: str, *, allow_empty: bool = False
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise AgUiProjectionError(f"durable payload field {key!r} must be text")
    if not allow_empty and not value.strip():
        raise AgUiProjectionError(f"durable payload field {key!r} must not be blank")
    return value


def optional_payload_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def json_text(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise AgUiProjectionError("tool arguments are not JSON serializable") from exc
