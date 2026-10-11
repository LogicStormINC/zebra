from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelThinkingMode,
)
from agent_core.domain.tools import ToolCall
from agent_core.ports.model_gateway import ModelResponseRejectedError

from agent_integrations.deepseek_profiles import (
    ResolvedDeepSeekInvocation,
)
from agent_integrations.deepseek_responses_payloads import (
    parse_usage,
)
from agent_integrations.model_errors import ModelProviderError
from agent_integrations.openai_payloads import (
    optional_int,
    optional_str,
)
from agent_integrations.request_metadata import ModelRequestMetadata


def parse_responses_completion(
    payload: dict[str, Any],
    *,
    resolved: ResolvedDeepSeekInvocation,
    request_metadata: ModelRequestMetadata,
    internal_names: Mapping[str, str],
    tools_advertised: bool,
    latency_ms: int,
    retry_count: int,
) -> ModelCompletion:
    try:
        return _parse_responses_completion(
            payload,
            resolved=resolved,
            request_metadata=request_metadata,
            internal_names=internal_names,
            tools_advertised=tools_advertised,
            latency_ms=latency_ms,
            retry_count=retry_count,
        )
    except ModelResponseRejectedError:
        raise
    except ValueError as exc:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        raise ModelResponseRejectedError(
            "invalid_responses_payload",
            phase="response_payload",
            retryable=True,
            payload_size=len(encoded),
            payload_sha256=hashlib.sha256(encoded).hexdigest(),
        ) from exc


def _parse_responses_completion(
    payload: dict[str, Any],
    *,
    resolved: ResolvedDeepSeekInvocation,
    request_metadata: ModelRequestMetadata,
    internal_names: Mapping[str, str],
    tools_advertised: bool,
    latency_ms: int,
    retry_count: int,
) -> ModelCompletion:
    status = optional_str(payload.get("status"))
    if status == "failed":
        raise ModelProviderError("provider_response_failed", retryable=True)
    if status == "incomplete":
        details = payload.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        normalized = "output_truncated" if reason == "max_output_tokens" else "content_filtered"
        raise ModelResponseRejectedError(normalized, phase="response_status", retryable=False)
    if status != "completed":
        raise ValueError("DeepSeek Responses terminal status is not completed")
    output = payload.get("output")
    if not isinstance(output, list):
        raise ValueError("DeepSeek Responses output must be a list")
    reasoning_parts: list[str] = []
    reasoning_seen = False
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for item in output:
        if not isinstance(item, dict):
            raise ValueError("DeepSeek Responses output item must be an object")
        item_type = item.get("type")
        if item_type == "reasoning":
            reasoning_seen = True
            reasoning_parts.extend(_content_text(item.get("content"), "reasoning_text"))
        elif item_type == "message":
            text_parts.extend(_content_text(item.get("content"), "output_text"))
        elif item_type == "function_call":
            tool_calls.append(_function_call(item, internal_names))
        elif item_type == "web_search_call":
            raise ModelResponseRejectedError(
                "provider_side_tool_not_allowed",
                phase="output_item",
                retryable=False,
            )
        else:
            raise ModelResponseRejectedError(
                "unsupported_responses_output_item",
                phase="output_item",
                retryable=False,
            )
    reasoning = "".join(reasoning_parts) if reasoning_seen else None
    thinking_with_tools = bool(
        tools_advertised and resolved.thinking_mode is ModelThinkingMode.ENABLED
    )
    requires_reasoning = thinking_with_tools and reasoning is not None
    content = "".join(text_parts).strip()
    if not content:
        if tool_calls:
            content = "Tool calls proposed."
        else:
            raise ValueError("DeepSeek Responses returned no public text or function call")
    usage = parse_usage(payload.get("usage"))
    model_name = optional_str(payload.get("model")) or resolved.profile.model
    finish_reason = "tool_calls" if tool_calls else "stop"
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=datetime.now(UTC),
            tool_calls=tuple(tool_calls),
            metadata={"provider_reasoning_required": True} if requires_reasoning else {},
            provider_reasoning_content=reasoning,
        ),
        tool_calls=tuple(tool_calls),
        call_metadata=ModelCallMetadata(
            model_call_id=optional_str(payload.get("id")),
            provider="deepseek",
            model_name=model_name,
            latency_ms=latency_ms,
            cache_hit=(
                usage.prompt_cache_hit_tokens > 0
                if usage.prompt_cache_hit_tokens is not None
                else None
            ),
            profile_id=resolved.profile.profile_id,
            profile_version_observed_at=resolved.profile.version_observed_at,
            requested_model=resolved.profile.model,
            resolved_model=model_name,
            role=resolved.role.value,
            thinking_mode=resolved.thinking_mode.value,
            reasoning_effort=(
                resolved.reasoning_effort.value if resolved.reasoning_effort else None
            ),
            tool_choice=resolved.tool_choice.value,
            prompt_version=request_metadata.prompt_version,
            tool_schema_bytes=request_metadata.tool_schema_bytes,
            tool_schema_hash=request_metadata.tool_schema_hash,
            stable_prefix_hash=request_metadata.stable_prefix_hash,
            request_hash=request_metadata.request_hash,
            message_count=request_metadata.message_count,
            message_prefix_hashes=request_metadata.message_prefix_hashes,
            finish_reason=finish_reason,
            time_to_first_event_ms=optional_int(payload.get("_zebra_time_to_first_event_ms")),
            time_to_first_public_text_ms=optional_int(
                payload.get("_zebra_time_to_first_public_text_ms")
            ),
            retry_count=retry_count,
            usage=usage,
        ),
    )


def _content_text(value: object, expected_type: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("DeepSeek Responses content must be a list")
    parts: list[str] = []
    for part in value:
        if not isinstance(part, dict) or part.get("type") != expected_type:
            continue
        text = part.get("text")
        if not isinstance(text, str):
            raise ValueError("DeepSeek Responses content text must be a string")
        parts.append(text)
    return parts


def _function_call(item: dict[str, Any], internal_names: Mapping[str, str]) -> ToolCall:
    call_id = optional_str(item.get("call_id"))
    provider_name = optional_str(item.get("name"))
    arguments = item.get("arguments")
    if call_id is None or provider_name is None or not isinstance(arguments, str):
        raise ValueError("DeepSeek Responses function call is incomplete")
    try:
        internal_name = internal_names[provider_name]
    except KeyError as exc:
        raise ModelResponseRejectedError(
            "unadvertised_tool_call",
            phase="tool_name",
            retryable=True,
            provider_tool_name=provider_name,
            provider_call_id=call_id,
        ) from exc
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        encoded = arguments.encode()
        raise ModelResponseRejectedError(
            "invalid_tool_arguments_json",
            phase="tool_arguments",
            retryable=True,
            provider_tool_name=provider_name,
            provider_call_id=call_id,
            error_position=exc.pos,
            payload_size=len(encoded),
            payload_sha256=hashlib.sha256(encoded).hexdigest(),
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek Responses function arguments must be an object")
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=internal_name,
        arguments=parsed,
        created_at=datetime.now(UTC),
        provider_call_id=call_id,
        provider_tool_name=provider_name,
        provider_arguments=parsed,
    )
