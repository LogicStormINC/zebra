from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

MemoryProvider = Literal["disabled", "mem0", "redis_agent_memory"]
MemoryRollout = Literal["off", "shadow", "active"]


@dataclass(frozen=True, slots=True)
class MemoryGatewaySettings:
    provider: MemoryProvider = "disabled"
    rollout: MemoryRollout = "off"
    endpoint: str | None = None
    store_id: str | None = None
    api_key_env: str = "REDIS_AGENT_MEMORY_API_KEY"
    generation: int = 1
    timeout_seconds: float = 5.0
    data_export_authorized: bool = False
    allow_insecure_http: bool = False

    @property
    def enabled(self) -> bool:
        return self.provider == "redis_agent_memory" and self.rollout != "off"


def load_memory_gateway_settings(values: Mapping[str, str]) -> MemoryGatewaySettings:
    provider = _choice(
        values,
        "ZEBRA_MEMORY_PROVIDER",
        default="disabled",
        choices={"disabled", "mem0", "redis_agent_memory"},
    )
    rollout = _choice(
        values,
        "ZEBRA_MEMORY_ROLLOUT",
        default="off",
        choices={"off", "shadow", "active"},
    )
    endpoint = _optional(values, "ZEBRA_REDIS_AGENT_MEMORY_ENDPOINT")
    store_id = _optional(values, "ZEBRA_REDIS_AGENT_MEMORY_STORE_ID")
    api_key_env = values.get(
        "ZEBRA_REDIS_AGENT_MEMORY_API_KEY_ENV",
        "REDIS_AGENT_MEMORY_API_KEY",
    ).strip()
    generation = _positive_int(values, "ZEBRA_MEMORY_GENERATION", default=1)
    timeout_seconds = _positive_float(
        values,
        "ZEBRA_MEMORY_TIMEOUT_SECONDS",
        default=5.0,
    )
    export_authorized = _bool(values, "ZEBRA_MEMORY_DATA_EXPORT_AUTHORIZED")
    allow_insecure = _bool(values, "ZEBRA_MEMORY_ALLOW_INSECURE_HTTP")

    if provider == "disabled" and rollout != "off":
        raise ValueError("disabled Memory provider requires ZEBRA_MEMORY_ROLLOUT=off")
    if provider == "mem0" and rollout != "off":
        raise ValueError("Mem0 runtime admission is denied; keep ZEBRA_MEMORY_ROLLOUT=off")
    if provider == "redis_agent_memory" and rollout != "off":
        if endpoint is None or store_id is None:
            raise ValueError("Redis Agent Memory rollout requires endpoint and Store ID")
        if not api_key_env or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", api_key_env):
            raise ValueError("ZEBRA_REDIS_AGENT_MEMORY_API_KEY_ENV is invalid")
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Redis Agent Memory endpoint must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Redis Agent Memory endpoint must not contain credentials")
        if parsed.scheme == "http" and not allow_insecure:
            raise ValueError("Redis Agent Memory HTTP requires explicit insecure opt-in")
        if not export_authorized:
            raise ValueError(
                "Redis Agent Memory rollout requires explicit data export authorization"
            )
    return MemoryGatewaySettings(
        provider=cast(MemoryProvider, provider),
        rollout=cast(MemoryRollout, rollout),
        endpoint=endpoint,
        store_id=store_id,
        api_key_env=api_key_env,
        generation=generation,
        timeout_seconds=timeout_seconds,
        data_export_authorized=export_authorized,
        allow_insecure_http=allow_insecure,
    )


def _choice(
    values: Mapping[str, str],
    key: str,
    *,
    default: str,
    choices: set[str],
) -> str:
    value = values.get(key, default).strip() or default
    if value not in choices:
        raise ValueError(f"{key} must be one of {', '.join(sorted(choices))}")
    return value


def _optional(values: Mapping[str, str], key: str) -> str | None:
    value = values.get(key, "").strip()
    return value.rstrip("/") or None


def _positive_int(values: Mapping[str, str], key: str, *, default: int) -> int:
    try:
        value = int(values.get(key, str(default)).strip())
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{key} must be positive")
    return value


def _positive_float(values: Mapping[str, str], key: str, *, default: float) -> float:
    try:
        value = float(values.get(key, str(default)).strip())
    except ValueError as exc:
        raise ValueError(f"{key} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _bool(values: Mapping[str, str], key: str) -> bool:
    return values.get(key, "").strip().lower() in {"1", "true", "yes", "on"}
