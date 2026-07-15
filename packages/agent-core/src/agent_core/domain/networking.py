from enum import StrEnum


class NetworkProfileName(StrEnum):
    NONE = "none"
    SETUP_ONLY = "setup-only"
    DOMAIN_ALLOWLIST = "domain-allowlist"
    MCP_PROXY_ONLY = "mcp-proxy-only"
    GIT_PROXY_ONLY = "git-proxy-only"
    FULL_TRUSTED_LOCAL = "full-trusted-local"
