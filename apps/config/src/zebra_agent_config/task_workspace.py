from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from zebra_agent_config.settings import McpHttpServerSettings, McpServerSettings, ZebraAgentSettings


def task_workspace_root(settings: ZebraAgentSettings, task_id: str) -> Path:
    return settings.task_workspace_root.expanduser().resolve() / task_id


def with_task_workspace_root(
    servers: Sequence[McpServerSettings | McpHttpServerSettings],
    workspace_root: Path,
) -> tuple[McpServerSettings | McpHttpServerSettings, ...]:
    overlaid: list[McpServerSettings | McpHttpServerSettings] = []
    for server in servers:
        if isinstance(server, McpServerSettings) and _is_minimax_stdio_server(server):
            overlaid.append(
                replace(
                    server,
                    env={**(server.env or {}), "ZEBRA_WORKSPACE_ROOT": str(workspace_root)},
                )
            )
        else:
            overlaid.append(server)
    return tuple(overlaid)


def _is_minimax_stdio_server(server: McpServerSettings) -> bool:
    return server.name == "minimax" or Path(server.command).name == "minimax_mcp_server.py"
