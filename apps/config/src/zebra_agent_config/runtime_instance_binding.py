"""Opt-in process identity metadata; the key never enters settings or Bundle snapshots."""

import base64
from collections.abc import Mapping
from uuid import UUID


def runtime_instance_key(values: Mapping[str, str]) -> bytes:
    value = values.get("ZEBRA_RUNTIME_INSTANCE_BINDING_KEY", "")
    if len(value) != 50 or not value.startswith("rtbind_"):
        raise ValueError("INVALID_RUNTIME_INSTANCE_BINDING_KEY")
    try:
        raw = base64.b64decode(value[7:] + "=", altchars=b"-_", validate=True)
    except ValueError:
        raise ValueError("INVALID_RUNTIME_INSTANCE_BINDING_KEY") from None
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value[7:]:
        raise ValueError("INVALID_RUNTIME_INSTANCE_BINDING_KEY")
    return raw


def load_runtime_instance_id(values: Mapping[str, str]) -> str | None:
    value = values.get("ZEBRA_RUNTIME_INSTANCE_ID")
    if value is None:
        return None
    try:
        valid = str(UUID(value)) == value
    except ValueError:
        valid = False
    if not valid or not values.get("ZEBRA_RUNTIME_GATE_CONFIG"):
        raise ValueError("RUNTIME_INSTANCE_REQUIRES_CANONICAL_ID_AND_GATE")
    runtime_instance_key(values)
    return value
