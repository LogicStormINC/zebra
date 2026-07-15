from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
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
class ScmSettings:
    provider: str
    github_owner: str | None
    github_repo: str | None
    github_token_env: str | None
    github_api_base_url: str
    pull_request_dry_run: bool


@dataclass(frozen=True)
class ZebraAgentSettings:
    profile: str
    database_url: str
    api: ApiSettings
    model: ModelSettings
    scm: ScmSettings = field(
        default_factory=lambda: ScmSettings(
            provider="local-only",
            github_owner=None,
            github_repo=None,
            github_token_env=None,
            github_api_base_url="https://api.github.com",
            pull_request_dry_run=True,
        )
    )
    web_search_endpoint: str | None = None


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    defaults_path: Path | None = None,
) -> ZebraAgentSettings:
    values = dict(_read_defaults(defaults_path or Path("configs/default.env")))
    values.update(_read_defaults(Path(".env")))
    values.update(_read_defaults(Path(".env.local")))
    values.update(os.environ if env is None else env)
    provider = _read(values, "ZEBRA_MODEL_PROVIDER", default="deepseek")
    if provider == "deepseek":
        deepseek_base_url = _read_optional(values, "DEEPSEEK_BASE_URL")
        if deepseek_base_url:
            values["ZEBRA_MODEL_BASE_URL"] = deepseek_base_url
        deepseek_model = _read_optional(values, "DEEPSEEK_MODEL")
        if deepseek_model:
            values["ZEBRA_MODEL_NAME"] = deepseek_model
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
        scm=_load_scm_settings(values),
        web_search_endpoint=_read_optional(values, "ZEBRA_WEB_SEARCH_ENDPOINT"),
    )


def _load_scm_settings(values: Mapping[str, str]) -> ScmSettings:
    provider = _read(values, "ZEBRA_SCM_PROVIDER", default="local-only")
    github_owner = _read_optional(values, "ZEBRA_GITHUB_OWNER")
    github_repo = _read_optional(values, "ZEBRA_GITHUB_REPO")
    github_token_env = _read_optional(values, "ZEBRA_GITHUB_TOKEN_ENV")
    if provider == "github":
        if github_owner is None:
            raise ValueError("ZEBRA_GITHUB_OWNER is required when ZEBRA_SCM_PROVIDER=github")
        if github_repo is None:
            raise ValueError("ZEBRA_GITHUB_REPO is required when ZEBRA_SCM_PROVIDER=github")
        if github_token_env is None:
            raise ValueError("ZEBRA_GITHUB_TOKEN_ENV is required when ZEBRA_SCM_PROVIDER=github")
    return ScmSettings(
        provider=provider,
        github_owner=github_owner,
        github_repo=github_repo,
        github_token_env=github_token_env,
        github_api_base_url=_read(
            values,
            "ZEBRA_GITHUB_API_BASE_URL",
            default="https://api.github.com",
        ),
        pull_request_dry_run=_read_bool(
            values,
            "ZEBRA_SCM_PULL_REQUEST_DRY_RUN",
            default=True,
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


def _read_bool(values: Mapping[str, str], key: str, *, default: bool) -> bool:
    value = values.get(key, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}
