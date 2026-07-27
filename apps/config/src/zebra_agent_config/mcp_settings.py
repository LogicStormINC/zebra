from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

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
            servers.append(_read_stdio_mcp_server(name, entry, values))
        elif kind == "http":
            servers.append(_read_http_mcp_server(name, entry))
        else:
            raise ValueError(f"MCP server {name} has unsupported kind {kind!r}")
    return tuple(servers)


def _read_stdio_mcp_server(
    name: str,
    entry: Mapping[str, object],
    values: Mapping[str, str],
) -> McpServerSettings:
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
        env = {}
        for key, value in raw_env.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"MCP server {name} env key {key!r}")
            if isinstance(value, str):
                env[key] = values.get(value[1:], "") if value.startswith("$") else value
            else:
                raise ValueError(f"MCP server {name} env val {key!r} must be str")

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
        if not isinstance(bearer_token_env, str) or not _MCP_BEARER_ENV_RE.fullmatch(
            bearer_token_env
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
