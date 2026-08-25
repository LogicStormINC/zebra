from __future__ import annotations

import hashlib
import json
from typing import Any

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelUsage

from agent_integrations.openai_payloads import optional_int
from agent_integrations.request_metadata import ModelRequestMetadata

RESPONSES_PROMPT_VERSION = "zebra-deepseek-responses-v1"


def serialize_input(
    messages: list[SessionMessage],
) -> tuple[str, list[dict[str, object]]]:
    instructions: list[str] = []
    items: list[dict[str, object]] = []
    leading_system = True
    for message in messages:
        if leading_system and message.role is MessageRole.SYSTEM:
            instructions.append(message.content)
            continue
        leading_system = False
        if message.role is MessageRole.ASSISTANT:
            reasoning = message.provider_reasoning_content
            if message.metadata.get("provider_reasoning_required") is True and reasoning is None:
                raise ValueError("DeepSeek reasoning continuation is unavailable")
            if reasoning is not None:
                items.append(
                    {
                        "type": "reasoning",
                        "content": [{"type": "reasoning_text", "text": reasoning}],
                    }
                )
            content = "" if message.content == "Tool calls proposed." else message.content
            items.append({"type": "message", "role": "assistant", "content": content})
            for call in message.tool_calls:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.provider_call_id or str(call.tool_call_id),
                        "name": call.provider_tool_name or call.name.replace(".", "__"),
                        "arguments": json.dumps(
                            call.provider_arguments or call.arguments,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    }
                )
            continue
        if message.role is MessageRole.TOOL:
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content,
                }
            )
            continue
        items.append(
            {"type": "message", "role": message.role.value, "content": message.content}
        )
    return "\n\n".join(instructions), items


def request_metadata(body: dict[str, Any]) -> ModelRequestMetadata:
    tools = json.dumps(
        body.get("tools", []), sort_keys=True, separators=(",", ":")
    ).encode()
    stable = json.dumps(
        {
            "instructions": body.get("instructions"),
            "prompt_version": RESPONSES_PROMPT_VERSION,
            "tools": body.get("tools", []),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ModelRequestMetadata(
        prompt_version=RESPONSES_PROMPT_VERSION,
        tool_schema_bytes=len(tools),
        tool_schema_hash=hashlib.sha256(tools).hexdigest(),
        stable_prefix_hash=hashlib.sha256(stable).hexdigest(),
    )


def parse_usage(value: object) -> ModelUsage:
    if not isinstance(value, dict):
        return ModelUsage()
    input_details = value.get("input_tokens_details")
    output_details = value.get("output_tokens_details")
    if not isinstance(input_details, dict):
        input_details = {}
    if not isinstance(output_details, dict):
        output_details = {}
    input_tokens = optional_int(value.get("input_tokens"))
    cache_hits = optional_int(input_details.get("cached_tokens"))
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=optional_int(value.get("output_tokens")),
        total_tokens=optional_int(value.get("total_tokens")),
        reasoning_tokens=optional_int(output_details.get("reasoning_tokens")),
        prompt_cache_hit_tokens=cache_hits,
        prompt_cache_miss_tokens=(
            input_tokens - cache_hits
            if input_tokens is not None and cache_hits is not None
            else None
        ),
    )
