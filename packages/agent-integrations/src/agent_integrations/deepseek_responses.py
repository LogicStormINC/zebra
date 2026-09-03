from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import httpx
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelContextWindow,
    ModelInvocationPolicy,
    ModelTextDelta,
    ModelThinkingMode,
    ModelToolDefinition,
)
from agent_core.domain.tools import ToolCall
from agent_core.ports.model_gateway import ModelResponseRejectedError

from agent_integrations.deepseek_profiles import (
    DeepSeekProfileRouter,
    ResolvedDeepSeekInvocation,
)
from agent_integrations.deepseek_responses_payloads import (
    parse_usage,
    request_metadata,
    serialize_input,
)
from agent_integrations.deepseek_responses_streaming import (
    read_deepseek_responses_stream,
)
from agent_integrations.model_errors import ModelProviderError, normalize_provider_error
from agent_integrations.openai_payloads import (
    internal_tool_names,
    optional_int,
    optional_str,
    provider_tool_names,
)
from agent_integrations.request_metadata import ModelRequestMetadata

RESPONSES_PATH = "/responses"


class DeepSeekResponsesModelGateway:
    """Explicit text-profile adapter for DeepSeek's stateless Responses API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        max_retries: int = 1,
        deepseek_router: DeepSeekProfileRouter | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._max_retries = max_retries
        self._router = deepseek_router or DeepSeekProfileRouter(
            legacy_executor_model=model_name
        )
        self._client = client

    @property
    def context_window(self) -> ModelContextWindow:
        return self._router.resolve(
            ModelInvocationPolicy(),
            has_tools=False,
        ).profile.context_window

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        invocation_policy: ModelInvocationPolicy | None = None,
        strict_tools: bool = False,
    ) -> ModelCompletion:
        if strict_tools:
            raise ValueError("DeepSeek Responses does not expose strict tool mode")
        resolved, body, metadata, names = self._prepare(
            messages,
            tools=tools,
            invocation_policy=invocation_policy,
            stream=False,
        )
        started = perf_counter()
        retries = 0
        while True:
            try:
                payload = self._post(body)
                return parse_responses_completion(
                    payload,
                    resolved=resolved,
                    request_metadata=metadata,
                    internal_names=internal_tool_names(tools, names),
                    tools_advertised=bool(tools),
                    latency_ms=int((perf_counter() - started) * 1000),
                    retry_count=retries,
                )
            except Exception as exc:
                retries = self._retry_or_raise(
                    exc,
                    retries=retries,
                    messages=messages,
                    public_delta_emitted=False,
                )

    def complete_stream(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        on_text_delta: Callable[[ModelTextDelta], None],
        invocation_policy: ModelInvocationPolicy | None = None,
        strict_tools: bool = False,
    ) -> ModelCompletion:
        if strict_tools:
            raise ValueError("DeepSeek Responses does not expose strict tool mode")
        resolved, body, metadata, names = self._prepare(
            messages,
            tools=tools,
            invocation_policy=invocation_policy,
            stream=True,
        )
        client = self._client or httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))
        should_close = self._client is None
        started = perf_counter()
        retries = 0
        public_delta_emitted = False

        def emit(delta: ModelTextDelta) -> None:
            nonlocal public_delta_emitted
            public_delta_emitted = True
            on_text_delta(delta)

        try:
            while True:
                try:
                    payload = read_deepseek_responses_stream(
                        client,
                        url=f"{self._base_url}{RESPONSES_PATH}",
                        headers=self._headers(),
                        body=body,
                        on_text_delta=emit,
                    )
                    return parse_responses_completion(
                        payload,
                        resolved=resolved,
                        request_metadata=metadata,
                        internal_names=internal_tool_names(tools, names),
                        tools_advertised=bool(tools),
                        latency_ms=int((perf_counter() - started) * 1000),
                        retry_count=retries,
                    )
                except Exception as exc:
                    retries = self._retry_or_raise(
                        exc,
                        retries=retries,
                        messages=messages,
                        public_delta_emitted=public_delta_emitted,
                    )
        finally:
            if should_close:
                client.close()

    def _prepare(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...],
        invocation_policy: ModelInvocationPolicy | None,
        stream: bool,
    ) -> tuple[
        ResolvedDeepSeekInvocation,
        dict[str, Any],
        ModelRequestMetadata,
        tuple[str, ...],
    ]:
        resolved = self._router.resolve(
            invocation_policy or ModelInvocationPolicy(),
            has_tools=bool(tools),
        )
        if resolved.profile.model not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
            raise ValueError("DeepSeek Responses requires a supported text model profile")
        names = provider_tool_names(tools)
        serialized_tools = [
            {
                "type": "function",
                "name": name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            }
            for tool, name in zip(tools, names, strict=True)
        ]
        serialized_tools.sort(key=lambda tool: str(tool["name"]))
        instructions, input_items = serialize_input(messages)
        body: dict[str, Any] = {
            "model": resolved.profile.model,
            "input": input_items,
            "stream": stream,
            "max_output_tokens": resolved.max_output_tokens,
            "reasoning": {
                "effort": (
                    "none"
                    if resolved.thinking_mode is ModelThinkingMode.DISABLED
                    else (resolved.reasoning_effort.value if resolved.reasoning_effort else "high")
                )
            },
        }
        if instructions:
            body["instructions"] = instructions
        if serialized_tools:
            body["tools"] = serialized_tools
            body["tool_choice"] = resolved.tool_choice.value
        metadata = request_metadata(body)
        return resolved, body, metadata, names

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))
        should_close = self._client is None
        try:
            response = client.post(
                f"{self._base_url}{RESPONSES_PATH}",
                headers=self._headers(),
                json=body,
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                encoded = response.content
                raise ModelResponseRejectedError(
                    "invalid_responses_json",
                    phase="response_payload",
                    retryable=True,
                    payload_size=len(encoded),
                    payload_sha256=hashlib.sha256(encoded).hexdigest(),
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError("DeepSeek Responses payload must be an object")
            return payload
        finally:
            if should_close:
                client.close()

    def _retry_or_raise(
        self,
        exc: Exception,
        *,
        retries: int,
        messages: list[SessionMessage],
        public_delta_emitted: bool,
    ) -> int:
        if isinstance(exc, ModelResponseRejectedError):
            raise exc
        if isinstance(exc, ValueError) and not isinstance(exc, ModelProviderError):
            raise exc
        error = normalize_provider_error(exc)
        if (
            error.retryable
            and retries < self._max_retries
            and not public_delta_emitted
            and not any(message.role is MessageRole.TOOL for message in messages)
        ):
            return retries + 1
        raise ModelProviderError(
            error.normalized_error,
            retryable=error.retryable,
            retry_count=retries,
        ) from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }


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
    if thinking_with_tools and tool_calls and reasoning is None:
        raise ValueError("DeepSeek thinking tool request requires reasoning output")
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
            finish_reason=finish_reason,
            time_to_first_event_ms=optional_int(
                payload.get("_zebra_time_to_first_event_ms")
            ),
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
