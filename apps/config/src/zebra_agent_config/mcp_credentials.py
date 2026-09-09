"""Operator-only references to a mounted MCP encryption master key."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class McpCredentialSettings:
    enabled: bool = False
    secret_root: str = ""
    key_handle: str = ""
    key_version: str = ""
    refresh_enabled: bool = False
    worker_enabled: bool = False


def load_mcp_credentials(values: Mapping[str, str]) -> McpCredentialSettings:
    return McpCredentialSettings(
        enabled=values.get("ZEBRA_CLOUD_MCP_CREDENTIALS_ENABLED", "false").strip().lower()
        in {"true", "1", "yes", "on"},
        secret_root=values.get("ZEBRA_MCP_SECRET_ROOT", "").strip(),
        key_handle=values.get("ZEBRA_MCP_KEY_HANDLE", "").strip(),
        key_version=values.get("ZEBRA_MCP_KEY_VERSION", "").strip(),
        refresh_enabled=values.get("ZEBRA_CLOUD_MCP_REFRESH_ENABLED", "false").strip().lower()
        in {"true", "1", "yes", "on"},
        worker_enabled=values.get("ZEBRA_CLOUD_MCP_WORKER_ENABLED", "false").strip().lower()
        in {"true", "1", "yes", "on"},
    )
