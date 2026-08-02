from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from zebra_agent_config.mcp_settings import (
    McpHttpServerSettings as McpHttpServerSettings,
)
from zebra_agent_config.mcp_settings import (
    McpServerSettings as McpServerSettings,
)
from zebra_agent_config.mcp_settings import (
    _read_mcp_servers,
)
from zebra_agent_config.model_catalog import ModelCatalog, load_model_catalog
from zebra_agent_config.setup_settings import SetupSettings, load_setup_settings


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    api_key_env: str
    base_url: str
    model: str
    profile_id: str | None = None
    executor_profile: str | None = None
    planner_profile: str | None = None
    reviewer_profile: str | None = None
    summarizer_profile: str | None = None
    analyst_profile: str | None = None
    classifier_profile: str | None = None
    max_retries: int = 1
    deepseek_beta_enabled: bool = False
    deepseek_beta_base_url: str | None = None

@dataclass(frozen=True)
class ApiSettings:
    auth_token: str | None

@dataclass(frozen=True)
class SessionHandoffSettings:
    enabled: bool = False

@dataclass(frozen=True)
class ScmSettings:
    provider: str
    github_owner: str | None
    github_repo: str | None
    github_token_env: str | None
    github_api_base_url: str
    pull_request_dry_run: bool

@dataclass(frozen=True)
class RuntimeSettings:
    runtime_class: str = "trusted-local"
    engine: str = "docker"
    gvisor_runtime: str = "runsc"
    image: str = ""
    cpu_count: float = 2.0
    memory_mb: int = 2048
    pids: int = 256
    tmpfs_mb: int = 512
    max_output_bytes: int = 1_048_576
    max_execution_seconds: float = 900.0
    container_uid: int = 65532
    container_gid: int = 65532
    require_workspace_quota: bool = False
    workspace_quota_mb: int = 10_240


@dataclass(frozen=True)
class FinosJournalProviderSettings:
    base_url: str | None = None
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class ZebraAgentSettings:
    profile: str
    database_url: str
    api: ApiSettings
    model: ModelSettings
    model_catalog: ModelCatalog | None = None
    build_commit: str = "unknown"
    task_workspace_root: Path = Path(".zebra-agent/task-workspaces")
    finos_journal_provider: FinosJournalProviderSettings = field(
        default_factory=FinosJournalProviderSettings
    )
    session_handoff: SessionHandoffSettings = field(default_factory=SessionHandoffSettings)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    setup: SetupSettings = field(default_factory=SetupSettings)
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
    web_pipeline_v2: bool = False
    skill_roots: tuple[str, ...] = ()
    skill_roots_system: tuple[str, ...] = ()
    skill_roots_admin: tuple[str, ...] = ()
    skill_roots_repo: tuple[str, ...] = ()
    skills_state_path: str = ".zebra-agent/skills-state.sqlite"
    mcp_servers: tuple[McpServerSettings | McpHttpServerSettings, ...] = ()
    mcp_elicitation_enabled: bool = True

def trusted_local_mode_enabled(settings: ZebraAgentSettings) -> bool:
    return settings.profile == "local" and settings.runtime.runtime_class == "trusted-local"

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
    elif provider == "qwen":
        dashscope_base_url = _read_optional(values, "DASHSCOPE_BASE_URL")
        if dashscope_base_url:
            values["ZEBRA_MODEL_BASE_URL"] = dashscope_base_url
        elif values.get("ZEBRA_MODEL_BASE_URL") == "https://api.deepseek.com":
            values["ZEBRA_MODEL_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        dashscope_model = _read_optional(values, "DASHSCOPE_MODEL")
        if dashscope_model:
            values["ZEBRA_MODEL_NAME"] = dashscope_model
        elif values.get("ZEBRA_MODEL_NAME") == "deepseek-v4-flash":
            values["ZEBRA_MODEL_NAME"] = "qwen3.7-flash-2026-07-15"
        values["ZEBRA_MODEL_API_KEY_ENV"] = "DASHSCOPE_API_KEY"
    profile = _read(values, "ZEBRA_PROFILE", default="local")
    model = ModelSettings(
        provider=provider,
        api_key_env=_read(
            values,
            "ZEBRA_MODEL_API_KEY_ENV",
            default=f"{provider.upper()}_API_KEY",
        ),
        base_url=_read(
            values,
            "ZEBRA_MODEL_BASE_URL",
            default=(
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
                if provider == "qwen"
                else "https://api.deepseek.com"
            ),
        ),
        model=_read(
            values,
            "ZEBRA_MODEL_NAME",
            default=(
                "qwen3.7-flash-2026-07-15" if provider == "qwen" else "deepseek-v4-flash"
            ),
        ),
        profile_id=_read_optional(values, "ZEBRA_MODEL_PROFILE_ID"),
        executor_profile=_read_optional(values, "ZEBRA_DEEPSEEK_EXECUTOR_PROFILE"),
        planner_profile=_read_optional(values, "ZEBRA_DEEPSEEK_PLANNER_PROFILE"),
        reviewer_profile=_read_optional(values, "ZEBRA_DEEPSEEK_REVIEWER_PROFILE"),
        summarizer_profile=_read_optional(values, "ZEBRA_DEEPSEEK_SUMMARIZER_PROFILE"),
        analyst_profile=_read_optional(values, "ZEBRA_DEEPSEEK_ANALYST_PROFILE"),
        classifier_profile=_read_optional(values, "ZEBRA_DEEPSEEK_CLASSIFIER_PROFILE"),
        max_retries=_read_non_negative_int(
            values,
            "ZEBRA_MODEL_MAX_RETRIES",
            default=1,
        ),
        deepseek_beta_enabled=_read_bool(
            values,
            "ZEBRA_DEEPSEEK_BETA_ENABLED",
            default=False,
        ),
        deepseek_beta_base_url=_read_optional(values, "ZEBRA_DEEPSEEK_BETA_BASE_URL"),
    )
    return ZebraAgentSettings(
        profile=profile,
        database_url=_read(
            values,
            "ZEBRA_DATABASE_URL",
            default=".zebra-agent/sessions.sqlite",
        ),
        task_workspace_root=Path(
            _read(values, "ZEBRA_TASK_WORKSPACE_ROOT", default=".zebra-agent/task-workspaces")
        ),
        api=ApiSettings(
            auth_token=_read_optional(values, "ZEBRA_API_AUTH_TOKEN"),
        ),
        model=model,
        model_catalog=load_model_catalog(
            _read_optional(values, "ZEBRA_MODEL_CATALOG_JSON"),
            model,
        ),
        finos_journal_provider=_load_finos_journal_provider_settings(values),
        build_commit=_read(values, "ZEBRA_BUILD_COMMIT", default="unknown"),
        session_handoff=SessionHandoffSettings(
            enabled=_read_bool(values, "ZEBRA_SESSION_HANDOFF_ENABLED", default=False),
        ),
        runtime=_load_runtime_settings(values, profile=profile),
        setup=load_setup_settings(values),
        scm=_load_scm_settings(values),
        web_search_endpoint=_read_optional(values, "ZEBRA_WEB_SEARCH_ENDPOINT"),
        web_pipeline_v2=_read_bool(values, "ZEBRA_WEB_PIPELINE_V2", default=False),
        skill_roots=_read_paths(values, "ZEBRA_SKILL_ROOTS"),
        skill_roots_system=_read_paths(values, "ZEBRA_SKILL_ROOTS_SYSTEM"),
        skill_roots_admin=_read_paths(values, "ZEBRA_SKILL_ROOTS_ADMIN"),
        skill_roots_repo=_read_paths(values, "ZEBRA_SKILL_ROOTS_REPO"),
        skills_state_path=_read(
            values,
            "ZEBRA_SKILLS_STATE_PATH",
            default=".zebra-agent/skills-state.sqlite",
        ),
        mcp_servers=_read_mcp_servers(values),
        mcp_elicitation_enabled=_read_bool(values, "ZEBRA_MCP_ELICITATION", default=True),
    )


def _load_finos_journal_provider_settings(
    values: Mapping[str, str],
) -> FinosJournalProviderSettings:
    base_url = _read_optional(values, "ZEBRA_FINOS_JOURNAL_PROVIDER_BASE_URL")
    if base_url is not None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "ZEBRA_FINOS_JOURNAL_PROVIDER_BASE_URL must be a valid http or https URL"
            )
    return FinosJournalProviderSettings(
        base_url=base_url.rstrip("/") if base_url is not None else None,
        timeout_seconds=_read_float(
            values,
            "ZEBRA_FINOS_JOURNAL_PROVIDER_TIMEOUT_SECONDS",
            default=10.0,
        ),
    )


def _load_runtime_settings(
    values: Mapping[str, str],
    *,
    profile: str,
) -> RuntimeSettings:
    runtime_class = _read(
        values,
        "ZEBRA_RUNTIME_CLASS",
        default="gvisor" if profile == "production" else "trusted-local",
    )
    if runtime_class not in {"trusted-local", "os-sandbox", "oci-rootless", "gvisor"}:
        raise ValueError("ZEBRA_RUNTIME_CLASS is unsupported")
    if profile == "production" and runtime_class != "gvisor":
        raise ValueError("ZEBRA_PROFILE=production requires ZEBRA_RUNTIME_CLASS=gvisor")
    engine = _read(values, "ZEBRA_RUNTIME_ENGINE", default="docker")
    if engine not in {"docker", "podman"}:
        raise ValueError("ZEBRA_RUNTIME_ENGINE must be docker or podman")
    gvisor_runtime = _read(values, "ZEBRA_GVISOR_RUNTIME", default="runsc")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", gvisor_runtime):
        raise ValueError("ZEBRA_GVISOR_RUNTIME is invalid")
    image = _read_optional(values, "ZEBRA_RUNTIME_IMAGE") or ""
    if runtime_class in {"oci-rootless", "gvisor"} and not re.fullmatch(
        r".+@sha256:[0-9a-fA-F]{64}", image
    ):
        raise ValueError("ZEBRA_RUNTIME_IMAGE must be pinned by sha256 digest")
    require_workspace_quota = _read_bool(
        values,
        "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA",
        default=profile == "production",
    )
    if profile == "production" and not require_workspace_quota:
        raise ValueError("ZEBRA_PROFILE=production requires a storage-enforced workspace quota")
    return RuntimeSettings(
        runtime_class=runtime_class,
        engine=engine,
        gvisor_runtime=gvisor_runtime,
        image=image,
        cpu_count=_read_float(values, "ZEBRA_RUNTIME_CPUS", default=2.0),
        memory_mb=_read_int(values, "ZEBRA_RUNTIME_MEMORY_MB", default=2048),
        pids=_read_int(values, "ZEBRA_RUNTIME_PIDS", default=256),
        tmpfs_mb=_read_int(values, "ZEBRA_RUNTIME_TMPFS_MB", default=512),
        max_output_bytes=_read_int(
            values,
            "ZEBRA_RUNTIME_MAX_OUTPUT_BYTES",
            default=1_048_576,
        ),
        max_execution_seconds=_read_float(
            values,
            "ZEBRA_RUNTIME_MAX_EXECUTION_SECONDS",
            default=900.0,
        ),
        container_uid=_read_int(values, "ZEBRA_RUNTIME_UID", default=65532),
        container_gid=_read_int(values, "ZEBRA_RUNTIME_GID", default=65532),
        require_workspace_quota=require_workspace_quota,
        workspace_quota_mb=_read_int(
            values,
            "ZEBRA_RUNTIME_WORKSPACE_QUOTA_MB",
            default=10_240,
        ),
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


def _read_int(values: Mapping[str, str], key: str, *, default: int) -> int:
    raw = values.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _read_non_negative_int(values: Mapping[str, str], key: str, *, default: int) -> int:
    raw = values.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{key} must not be negative")
    return value


def _read_float(values: Mapping[str, str], key: str, *, default: float) -> float:
    raw = values.get(key, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _read_paths(values: Mapping[str, str], key: str) -> tuple[str, ...]:
    value = values.get(key, "").strip()
    if not value:
        return ()
    roots: list[str] = []
    for raw_path in value.split(os.pathsep):
        path = Path(raw_path.strip()).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"{key} contains a missing path: {path}") from exc
        if not resolved.is_dir():
            raise ValueError(f"{key} contains a non-directory path: {path}")
        normalized = str(resolved)
        if normalized in roots:
            raise ValueError(f"{key} contains a duplicate path: {normalized}")
        roots.append(normalized)
    return tuple(roots)


def _read_bool(values: Mapping[str, str], key: str, *, default: bool) -> bool:
    value = values.get(key, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}
