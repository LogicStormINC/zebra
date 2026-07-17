from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agent_integrations.deepseek_profiles import ResolvedDeepSeekInvocation


@dataclass(frozen=True)
class ModelRequestMetadata:
    prompt_version: str
    tool_schema_bytes: int
    tool_schema_hash: str
    stable_prefix_hash: str


def build_request_metadata(
    body: dict[str, Any],
    resolved: ResolvedDeepSeekInvocation,
) -> ModelRequestMetadata:
    tools = body.get("tools", [])
    messages = body.get("messages", [])
    system_messages = [
        message
        for message in messages
        if isinstance(message, dict) and message.get("role") == "system"
    ]
    tool_schema = _canonical_json(tools)
    stable_prefix = _canonical_json(
        {
            "prompt_version": resolved.profile.prompt_version,
            "system_messages": system_messages,
            "tools": tools,
        }
    )
    return ModelRequestMetadata(
        prompt_version=resolved.profile.prompt_version,
        tool_schema_bytes=len(tool_schema),
        tool_schema_hash=hashlib.sha256(tool_schema).hexdigest(),
        stable_prefix_hash=hashlib.sha256(stable_prefix).hexdigest(),
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
