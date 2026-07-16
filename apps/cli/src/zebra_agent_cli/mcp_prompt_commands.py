from __future__ import annotations

from collections.abc import Sequence

from agent_runtime import discover_mcp_prompts
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_cli.cli_types import CliCommandResult


def mcp_prompt_inventory(settings: ZebraAgentSettings) -> CliCommandResult:
    if not settings.mcp_servers:
        payload: dict[str, object] = {
            "status": "unconfigured",
            "configured": False,
            "available": False,
            "prompt_count": 0,
            "prompts": [],
        }
    else:
        try:
            prompts = discover_mcp_prompts(settings.mcp_servers)
        except ValueError as error:
            return CliCommandResult(
                command="mcp-prompts",
                payload={
                    "status": "unavailable",
                    "configured": True,
                    "available": False,
                    "prompt_count": 0,
                    "prompts": [],
                    "reason": str(error),
                },
            )
        payload = {
            "status": "available",
            "configured": True,
            "available": True,
            "prompt_count": len(prompts),
            "prompts": [{**prompt.to_safe_mapping(), "available": True} for prompt in prompts],
        }
    return CliCommandResult(command="mcp-prompts", payload=payload)


def parse_mcp_prompt_selection(
    prompt_ids: Sequence[str],
    raw_arguments: Sequence[str],
) -> tuple[str | None, dict[str, str]]:
    if len(prompt_ids) > 1:
        raise ValueError("--mcp-prompt accepts at most one prompt ID")
    prompt_id = prompt_ids[0].strip() if prompt_ids else None
    if prompt_id == "":
        raise ValueError("--mcp-prompt must not be blank")
    arguments: dict[str, str] = {}
    for raw_argument in raw_arguments:
        name, separator, value = raw_argument.partition("=")
        if not separator or not name or name != name.strip():
            raise ValueError("--mcp-prompt-arg must use NAME=VALUE")
        if name in arguments:
            raise ValueError(f"duplicate MCP prompt argument: {name}")
        arguments[name] = value
    if arguments and prompt_id is None:
        raise ValueError("--mcp-prompt-arg requires --mcp-prompt")
    return prompt_id, arguments
