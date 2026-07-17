from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelToolDefinition,
    ModelUsage,
)
from agent_core.domain.tools import ToolCall

from agent_integrations.deepseek_profiles import ResolvedDeepSeekInvocation
from agent_integrations.model_errors import finish_reason_error
from agent_integrations.request_metadata import ModelRequestMetadata


def serialize_message(message: SessionMessage) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": message.role.value,
        "content": message.content,
    }
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tool_call.provider_call_id or str(tool_call.tool_call_id),
                "type": "function",
                "function": {
                    "name": provider_tool_name(tool_call.provider_tool_name or tool_call.name),
                    "arguments": json.dumps(
                        tool_call.provider_arguments
                        if tool_call.provider_arguments is not None
                        else tool_call.arguments,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                },
            }
            for tool_call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    return payload


def provider_tool_name(name: str) -> str:
    return name.replace(".", "__")


def provider_tool_names(tools: tuple[ModelToolDefinition, ...]) -> tuple[str, ...]:
    names = tuple(provider_tool_name(tool.name) for tool in tools)
    if len(set(names)) != len(names):
        raise ValueError("model tool names collide after provider normalization")
    for name in names:
        if (
            not name
            or len(name) > 64
            or any(
                not (character.isascii() and (character.isalnum() or character in "_-"))
                for character in name
            )
        ):
            raise ValueError(f"model tool name is not provider compatible: {name}")
    return names


def serialize_tool(
    tool: ModelToolDefinition,
    *,
    provider_name: str,
) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": provider_name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def internal_tool_names(
    tools: tuple[ModelToolDefinition, ...],
    tool_names: tuple[str, ...],
) -> dict[str, str]:
    return {provider_name: tool.name for tool, provider_name in zip(tools, tool_names, strict=True)}


def parse_completion(
    payload: dict[str, Any],
    *,
    provider_name: str,
    default_model_name: str,
    latency_ms: int,
    retry_count: int = 0,
    resolved: ResolvedDeepSeekInvocation | None = None,
    request_metadata: ModelRequestMetadata | None = None,
    internal_names: Mapping[str, str] | None = None,
) -> ModelCompletion:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("model gateway response must include at least one choice")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("model gateway choice must be an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("model gateway choice must include a message object")
    finish_reason = optional_str(first_choice.get("finish_reason"))
    if resolved is not None:
        finish_error = finish_reason_error(finish_reason)
        if finish_error is not None:
            raise finish_error
    tool_calls = _parse_tool_calls(
        message.get("tool_calls"),
        internal_tool_names=internal_names or {},
    )
    content = _assistant_content(message.get("content"), has_tool_calls=bool(tool_calls))
    usage = _parse_usage(payload.get("usage"))
    resolved_model = optional_str(payload.get("model")) or (
        resolved.profile.model if resolved else default_model_name
    )
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=datetime.now(UTC),
            tool_calls=tuple(tool_calls),
        ),
        tool_calls=tuple(tool_calls),
        call_metadata=ModelCallMetadata(
            model_call_id=optional_str(payload.get("id")),
            provider=provider_name,
            model_name=resolved_model,
            latency_ms=latency_ms,
            cache_hit=(
                usage.prompt_cache_hit_tokens > 0
                if usage.prompt_cache_hit_tokens is not None
                else None
            ),
            profile_id=resolved.profile.profile_id if resolved else None,
            profile_version_observed_at=(
                resolved.profile.version_observed_at if resolved else None
            ),
            requested_model=resolved.profile.model if resolved else default_model_name,
            resolved_model=resolved_model,
            role=resolved.role.value if resolved else None,
            thinking_mode=resolved.thinking_mode.value if resolved else None,
            reasoning_effort=(
                resolved.reasoning_effort.value if resolved and resolved.reasoning_effort else None
            ),
            tool_choice=resolved.tool_choice.value if resolved else None,
            prompt_version=(request_metadata.prompt_version if request_metadata else None),
            tool_schema_bytes=(request_metadata.tool_schema_bytes if request_metadata else None),
            tool_schema_hash=(request_metadata.tool_schema_hash if request_metadata else None),
            stable_prefix_hash=(request_metadata.stable_prefix_hash if request_metadata else None),
            finish_reason=finish_reason,
            time_to_first_event_ms=optional_int(payload.get("_zebra_time_to_first_event_ms")),
            time_to_first_public_text_ms=optional_int(
                payload.get("_zebra_time_to_first_public_text_ms")
            ),
            system_fingerprint=optional_str(payload.get("system_fingerprint")),
            retry_count=retry_count,
            usage=usage,
        ),
    )


def _assistant_content(value: object, *, has_tool_calls: bool) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if has_tool_calls:
        return "Tool calls proposed."
    raise ValueError("model gateway assistant message content must not be blank")


def _parse_tool_calls(
    value: object,
    *,
    internal_tool_names: Mapping[str, str],
) -> list[ToolCall]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("tool_calls must be a list when present")
    parsed: list[ToolCall] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("tool_call entry must be an object")
        function = item.get("function")
        if not isinstance(function, dict):
            raise ValueError("tool_call must include a function object")
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool_call function name must not be blank")
        provider_call_id = item.get("id")
        if not isinstance(provider_call_id, str) or not provider_call_id.strip():
            raise ValueError("tool_call id must not be blank")
        if internal_tool_names:
            try:
                name = internal_tool_names[name]
            except KeyError as exc:
                raise ValueError(f"model returned an unadvertised tool call: {name}") from exc
        parsed.append(
            ToolCall(
                tool_call_id=new_tool_call_id(),
                name=name,
                arguments=_parse_tool_arguments(function.get("arguments")),
                created_at=datetime.now(UTC),
                provider_call_id=provider_call_id,
            )
        )
    return parsed


def _parse_tool_arguments(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("tool_call arguments JSON must decode to an object")
        return parsed
    raise ValueError("tool_call arguments must be an object or JSON string")


def _parse_usage(value: object) -> ModelUsage:
    if not isinstance(value, dict):
        return ModelUsage()
    completion_details = value.get("completion_tokens_details")
    if not isinstance(completion_details, dict):
        completion_details = {}
    prompt_details = value.get("prompt_tokens_details")
    if not isinstance(prompt_details, dict):
        prompt_details = {}
    return ModelUsage(
        input_tokens=optional_int(value.get("prompt_tokens")),
        output_tokens=optional_int(value.get("completion_tokens")),
        total_tokens=optional_int(value.get("total_tokens")),
        reasoning_tokens=optional_int(completion_details.get("reasoning_tokens")),
        prompt_cache_hit_tokens=_first_optional_int(
            value.get("prompt_cache_hit_tokens"),
            prompt_details.get("cached_tokens"),
        ),
        prompt_cache_miss_tokens=optional_int(value.get("prompt_cache_miss_tokens")),
    )


def _first_optional_int(*values: object) -> int | None:
    for value in values:
        parsed = optional_int(value)
        if parsed is not None:
            return parsed
    return None


def optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("usage token fields must be integers")
    return value


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("string fields must be strings when present")
    return value.strip() or None
