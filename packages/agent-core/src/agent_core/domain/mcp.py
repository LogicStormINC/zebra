from __future__ import annotations

import re
from collections.abc import Sequence

MAX_MCP_ALLOWLIST_TOOLS = 32
_MCP_TOOL_NAME = re.compile(
    r"^mcp\.[A-Za-z][A-Za-z0-9_-]{0,31}\.[A-Za-z][A-Za-z0-9_-]{0,31}$"
)


def normalize_mcp_allowlist(value: Sequence[str]) -> tuple[str, ...]:
    if len(value) > MAX_MCP_ALLOWLIST_TOOLS:
        raise ValueError(f"mcp_allowlist accepts at most {MAX_MCP_ALLOWLIST_TOOLS} tools")
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, str) or not _MCP_TOOL_NAME.fullmatch(entry):
            raise ValueError("mcp_allowlist entries must be canonical mcp.<server>.<tool> names")
        if entry in seen:
            raise ValueError("mcp_allowlist entries must be unique")
        seen.add(entry)
        normalized.append(entry)
    return tuple(sorted(normalized))
