from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    api_key_env: str
    base_url: str
    model: str


@dataclass(frozen=True)
class ApiSettings:
    auth_token: str | None


@dataclass(frozen=True)
class ZebraAgentSettings:
    profile: str
    database_url: str
    api: ApiSettings
    model: ModelSettings


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    defaults_path: Path | None = None,
) -> ZebraAgentSettings:
    values = dict(_read_defaults(defaults_path or Path("configs/default.env")))
    values.update(env or os.environ)
    provider = _read(values, "ZEBRA_MODEL_PROVIDER", default="deepseek")
    return ZebraAgentSettings(
        profile=_read(values, "ZEBRA_PROFILE", default="local"),
        database_url=_read(
            values,
            "ZEBRA_DATABASE_URL",
            default=".zebra-agent/sessions.sqlite",
        ),
        api=ApiSettings(
            auth_token=_read_optional(values, "ZEBRA_API_AUTH_TOKEN"),
        ),
        model=ModelSettings(
            provider=provider,
            api_key_env=_read(
                values,
                "ZEBRA_MODEL_API_KEY_ENV",
                default=f"{provider.upper()}_API_KEY",
            ),
            base_url=_read(values, "ZEBRA_MODEL_BASE_URL", default="https://api.deepseek.com"),
            model=_read(values, "ZEBRA_MODEL_NAME", default="deepseek-v4-flash"),
        ),
    )


def _read_defaults(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    defaults: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        defaults[key.strip()] = value.strip()
    return defaults


def _read(values: Mapping[str, str], key: str, *, default: str) -> str:
    value = values.get(key, default).strip()
    if not value:
        return default
    return value


def _read_optional(values: Mapping[str, str], key: str) -> str | None:
    value = values.get(key, "").strip()
    if not value:
        return None
    return value
