from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.networking import NetworkProfileName
from agent_security import PolicyProfile


class McpAuthorityCommand(TypedDict):
    mcp_allowlist: tuple[str, ...]
    preapproved_readonly_tools: tuple[str, ...]


def parse_mcp_authority(
    payload: Mapping[str, object],
    *,
    policy_profile: str,
    network_profile: NetworkProfileName,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    mcp_allowlist = normalize_mcp_allowlist(_string_list(payload, "mcp_allowlist"))
    preapproved_readonly_tools = normalize_mcp_allowlist(
        _string_list(payload, "preapproved_readonly_tools")
    )
    if preapproved_readonly_tools and (
        policy_profile != PolicyProfile.READ_ONLY.value
        or network_profile is not NetworkProfileName.MCP_PROXY_ONLY
        or not set(preapproved_readonly_tools) <= set(mcp_allowlist)
    ):
        raise ValueError("preapproved read-only tools require scoped Task authority")
    return mcp_allowlist, preapproved_readonly_tools


def is_scoped(payload: Mapping[str, object]) -> bool:
    return (
        payload["policy_profile"] == PolicyProfile.READ_ONLY.value
        and payload["network_profile"] == NetworkProfileName.MCP_PROXY_ONLY.value
    )


def command_fields(payload: Mapping[str, object]) -> McpAuthorityCommand:
    return {
        "mcp_allowlist": tuple(cast(list[str], payload["mcp_allowlist"])),
        "preapproved_readonly_tools": tuple(
            cast(list[str], payload["preapproved_readonly_tools"])
        ),
    }


def response_fields(payload: Mapping[str, object]) -> dict[str, list[str]]:
    return {
        "mcp_allowlist": cast(list[str], payload["mcp_allowlist"]),
        "preapproved_readonly_tools": cast(
            list[str], payload["preapproved_readonly_tools"]
        ),
    }


def _string_list(payload: Mapping[str, object], field: str) -> list[str]:
    value = payload.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings when provided")
    return cast(list[str], value)
