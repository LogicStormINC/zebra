from __future__ import annotations

from agent_core.application import build_mcp_prompt_attachment
from agent_core.domain.attachments import TextAttachmentInput
from agent_runtime import McpServerSpec, resolve_mcp_prompt


def resolve_mcp_prompt_attachment(
    servers: tuple[McpServerSpec, ...],
    prompt_id: str | None,
    arguments: dict[str, str],
) -> tuple[TextAttachmentInput, ...]:
    if prompt_id is None:
        return ()
    resolved = resolve_mcp_prompt(servers, prompt_id, arguments)
    return (
        build_mcp_prompt_attachment(
            server_name=resolved.server_name,
            prompt_id=resolved.prompt_id,
            argument_names=tuple(name for name, _ in resolved.arguments),
            messages=tuple((message.role, message.text) for message in resolved.messages),
        ),
    )
