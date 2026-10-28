"""Explicit opt-in for a fixed, workload-authenticated Host control probe."""

import re
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class HostExecutionAuthoritySettings:
    enabled: bool = False
    tool_name: str = "host.authority"
    required_scope: str = "agent.run"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", self.tool_name):
            raise ValueError("invalid Host authority control tool")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", self.required_scope):
            raise ValueError("invalid Host authority scope")


def load_host_execution_authority(values: Mapping[str, str]) -> HostExecutionAuthoritySettings:
    enabled = values.get("ZEBRA_HOST_EXECUTION_AUTHORITY_ENABLED", "false").strip().lower()
    if enabled not in {"true", "false"}:
        raise ValueError("ZEBRA_HOST_EXECUTION_AUTHORITY_ENABLED must be true or false")
    return HostExecutionAuthoritySettings(
        enabled=enabled == "true",
        tool_name=values.get("ZEBRA_HOST_EXECUTION_AUTHORITY_TOOL", "host.authority"),
        required_scope=values.get("ZEBRA_HOST_EXECUTION_AUTHORITY_SCOPE", "agent.run"),
    )
