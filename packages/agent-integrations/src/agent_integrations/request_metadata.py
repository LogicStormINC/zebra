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
    request_hash: str
    message_count: int
    message_prefix_hashes: tuple[str, ...]


def build_request_metadata(
    body: dict[str, Any],
    resolved: ResolvedDeepSeekInvocation,
) -> ModelRequestMetadata:
    tools = body.get("tools", [])
    messages = body.get("messages", [])
    system_messages: list[object] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "system":
            break
        system_messages.append(message)
    tool_schema = _canonical_json(tools)
    stable_prefix = _canonical_json(
        {
            "prompt_version": resolved.profile.prompt_version,
            "system_messages": system_messages,
            "tools": tools,
        }
    )
    message_prefix_hashes = _prefix_hashes(messages)
    return ModelRequestMetadata(
        prompt_version=resolved.profile.prompt_version,
        tool_schema_bytes=len(tool_schema),
        tool_schema_hash=hashlib.sha256(tool_schema).hexdigest(),
        stable_prefix_hash=hashlib.sha256(stable_prefix).hexdigest(),
        request_hash=hashlib.sha256(_canonical_json(body)).hexdigest(),
        message_count=len(messages),
        message_prefix_hashes=message_prefix_hashes,
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _prefix_hashes(messages: object, *, limit: int = 256) -> tuple[str, ...]:
    if not isinstance(messages, list):
        return ()
    return tuple(
        hashlib.sha256(_canonical_json(messages[: index + 1])).hexdigest()
        for index in range(min(len(messages), limit))
    )
