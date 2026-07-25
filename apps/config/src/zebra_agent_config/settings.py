from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from zebra_agent_config.setup_settings import SetupSettings, load_setup_settings

MAX_MCP_SERVERS = 3
_MCP_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,19}$")
_MCP_BEARER_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_BLOCKED_MCP_EXECUTABLES = frozenset(
    {
        "bash",
        "cmd",
        "cmd.exe",
        "dash",
        "fish",
        "npx",
        "powershell",
        "powershell.exe",
        "pwsh",
        "sh",
        "uvx",
        "zsh",
    }
)

@dataclass(frozen=True)
class ModelSettings:
    provider: str
    api_key_env: str
    base_url: str
    model: str
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
class McpServerSettings:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None

@dataclass(frozen=True)
class McpHttpServerSettings:
    """A remote MCP server reached over Streamable HTTP.

    The bearer token is never stored: only the environment variable name that
    holds it, resolved by the transport at call time.
    """

    name: str
    url: str
    bearer_token_env: str | None = None

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
class ZebraAgentSettings:
    profile: str
    database_url: str
    api: ApiSettings
    model: ModelSettings
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
    profile = _read(values, "ZEBRA_PROFILE", default="local")
    return ZebraAgentSettings(
        profile=profile,
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
        ),
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
        mcp_elicitation_enabled=_read_bool(
            values, "ZEBRA_MCP_ELICITATION", default=True
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

def _read_mcp_servers(
    values: Mapping[str, str],
) -> tuple[McpServerSettings | McpHttpServerSettings, ...]:
    raw = values.get("ZEBRA_MCP_SERVERS", "").strip()
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("ZEBRA_MCP_SERVERS must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("ZEBRA_MCP_SERVERS must be a JSON object")
    if len(payload) > MAX_MCP_SERVERS:
        raise ValueError(f"ZEBRA_MCP_SERVERS supports at most {MAX_MCP_SERVERS} servers")
    servers: list[McpServerSettings | McpHttpServerSettings] = []
    for name in sorted(payload):
        if not isinstance(name, str) or not _MCP_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid MCP server name: {name!r}")
        entry = payload[name]
        if not isinstance(entry, dict):
            raise ValueError(f"MCP server {name} must be a JSON object")
        kind = entry.get("kind", "stdio")
        if kind == "stdio":
            servers.append(_read_stdio_mcp_server(name, entry))
        elif kind == "http":
            servers.append(_read_http_mcp_server(name, entry))
        else:
            raise ValueError(f"MCP server {name} has unsupported kind {kind!r}")
    return tuple(servers)

def _read_stdio_mcp_server(name: str, entry: Mapping[str, object]) -> McpServerSettings:
    extra = set(entry) - {"kind", "command", "args", "env"}
    if extra:
        raise ValueError(f"MCP server {name} supports only command and args")
    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"MCP server {name} requires command")
    command_path = Path(command).expanduser()
    if not command_path.is_absolute():
        raise ValueError(f"MCP server {name} command must be absolute")
    try:
        resolved_command = command_path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"MCP server {name} command does not exist") from exc
    if not resolved_command.is_file() or not os.access(resolved_command, os.X_OK):
        raise ValueError(f"MCP server {name} command must be executable")
    if resolved_command.name.lower() in _BLOCKED_MCP_EXECUTABLES:
        raise ValueError(f"MCP server {name} command is not allowed")
    args = _read_mcp_args(name, entry.get("args", []), resolved_command.name.lower())
    raw_env = entry.get("env", {})
    if not isinstance(raw_env, dict):
        raise ValueError(f"MCP server {name} env must be a JSON object")
    env: dict[str, str] | None = None
    if raw_env:
        env = dict(os.environ)
        for k, v in raw_env.items():
            if not isinstance(k, str) or not k:
                raise ValueError(f"MCP server {name} env key {k!r}")
            if isinstance(v, str):
                env[k] = os.environ.get(v[1:], "") if v.startswith("$") else v
            else:
                raise ValueError(f"MCP server {name} env val {k!r} must be str")
    
    return McpServerSettings(name=name, command=str(resolved_command), args=args, env=env)

def _read_http_mcp_server(name: str, entry: Mapping[str, object]) -> McpHttpServerSettings:
    extra = set(entry) - {"kind", "url", "bearer_token_env"}
    if extra:
        raise ValueError(f"MCP http server {name} supports only url and bearer_token_env")
    url = entry.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"MCP http server {name} requires a url")
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"MCP http server {name} url must be a valid https url")
    bearer_token_env = entry.get("bearer_token_env")
    if bearer_token_env is not None:
        if (
            not isinstance(bearer_token_env, str)
            or not _MCP_BEARER_ENV_RE.fullmatch(bearer_token_env)
        ):
            raise ValueError(f"MCP http server {name} bearer_token_env is invalid")
    return McpHttpServerSettings(
        name=name,
        url=url.strip(),
        bearer_token_env=bearer_token_env if isinstance(bearer_token_env, str) else None,
    )

def _read_mcp_args(name: str, value: object, executable: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError(f"MCP server {name} args must be a list with at most 16 entries")
    args: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 1024 or "\0" in item:
            raise ValueError(f"MCP server {name} contains an invalid argument")
        args.append(item)
    if sum(len(item) for item in args) > 4096:
        raise ValueError(f"MCP server {name} arguments are too large")
    if executable.startswith("python") and any(item in {"-c", "-m"} for item in args):
        raise ValueError(f"MCP server {name} cannot use inline Python execution")
    return tuple(args)

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
