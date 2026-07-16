from __future__ import annotations

import json
from collections.abc import Sequence

from agent_core.domain.attachments import TextAttachmentInput


def build_mcp_prompt_attachment(
    *,
    server_name: str,
    prompt_id: str,
    argument_names: Sequence[str],
    messages: Sequence[tuple[str, str]],
) -> TextAttachmentInput:
    normalized_messages = tuple(messages)
    if not normalized_messages:
        raise ValueError("MCP prompt capture requires at least one message")
    if any(
        role not in {"user", "assistant"} or not text.strip() for role, text in normalized_messages
    ):
        raise ValueError("MCP prompt capture contains an invalid message")
    payload = json.dumps(
        {
            "format": "zebra.mcp-prompt-capture.v1",
            "messages": [{"role": role, "text": text} for role, text in normalized_messages],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return TextAttachmentInput(
        file_name="mcp-prompt.json",
        media_type="application/json",
        payload=payload,
        source_type="mcp_prompt",
        source_server=server_name,
        source_id=prompt_id,
        source_argument_names=tuple(sorted(argument_names)),
    )
