from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any

import httpx
from agent_core.domain.identifiers import EventId
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import (
    ModelMediaCapabilities,
    ModelMediaInput,
    ModelMediaUnsupportedError,
    model_media_source_event_ids,
    ordered_media_inputs,
)
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelInvocationPolicy,
    ModelTextDelta,
    ModelThinkingMode,
    ModelToolDefinition,
)
from agent_core.ports.model_gateway import ModelMediaResolverPort, ModelResponseRejectedError
from zebra_agent_config import ZebraAgentSettings

from agent_integrations.deepseek_profiles import (
    DeepSeekProfileRouter,
    ResolvedDeepSeekInvocation,
)
from agent_integrations.deepseek_schema import validate_strict_tools
from agent_integrations.model_errors import ModelProviderError, normalize_provider_error
from agent_integrations.openai_payloads import (
    internal_tool_names,
    parse_completion,
    provider_tool_names,
    serialize_message,
    serialize_tool,
)
from agent_integrations.openai_streaming import read_openai_stream
from agent_integrations.request_metadata import (
    ModelRequestMetadata,
    build_request_metadata,
)

CHAT_COMPLETIONS_PATH = "/chat/completions"


class OpenAICompatibleModelGateway:
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_s: float = 30.0,
        max_retries: int = 1,
        deepseek_router: DeepSeekProfileRouter | None = None,
        media_capabilities: ModelMediaCapabilities | None = None,
        model_thinking_mode: ModelThinkingMode = ModelThinkingMode.DISABLED,
        media_resolver: ModelMediaResolverPort | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._deepseek_router = deepseek_router
        self._media_capabilities = media_capabilities or ModelMediaCapabilities()
        self._model_thinking_mode = model_thinking_mode
        self._media_resolver = media_resolver
        if provider_name.lower() == "deepseek" and deepseek_router is None:
            self._deepseek_router = DeepSeekProfileRouter(
                legacy_executor_model=model_name,
            )
        self._client = client

    @property
    def context_window(self) -> ModelContextWindow:
        if self._deepseek_router is None:
            return ModelContextWindow()
        return self._deepseek_router.resolve(
            ModelInvocationPolicy(),
            has_tools=False,
        ).profile.context_window

    @property
    def media_capabilities(self) -> ModelMediaCapabilities:
        return self._media_capabilities

    def estimate_media_tokens(self, media_inputs: tuple[ModelMediaInput, ...]) -> int:
        self._media_capabilities.validate_request(
            media_inputs,
            has_tools=False,
            streaming=False,
        )
        # ponytail: byte-based Qwen image estimate; replace with provider usage data if needed.
        return sum(max(256, (media.size_bytes + 511) // 512) for media in media_inputs)

    def bind_media_resolver(self, media_resolver: ModelMediaResolverPort) -> None:
        self._media_resolver = media_resolver

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        media_inputs: tuple[ModelMediaInput, ...] = (),
        invocation_policy: ModelInvocationPolicy | None = None,
        strict_tools: bool = False,
    ) -> ModelCompletion:
        self._validate_strict_mode(tools, strict_tools=strict_tools)
        tool_names = provider_tool_names(tools)
        resolved = self._resolve_deepseek(invocation_policy, has_tools=bool(tools))
        request_body, request_metadata = self._request_body(
            messages,
            tools=tools,
            media_inputs=media_inputs,
            tool_names=tool_names,
            stream=False,
            resolved=resolved,
            strict_tools=strict_tools,
        )
        started = perf_counter()
        retry_count = 0
        while True:
            try:
                response_data = self._post_chat_completion(request_body)
                return parse_completion(
                    response_data,
                    provider_name=self._provider_name,
                    default_model_name=self._model_name,
                    latency_ms=int((perf_counter() - started) * 1000),
                    retry_count=retry_count,
                    resolved=resolved,
                    request_metadata=request_metadata,
                    internal_names=internal_tool_names(tools, tool_names),
                )
            except Exception as exc:
                if isinstance(exc, ModelResponseRejectedError):
                    raise
                if isinstance(exc, ValueError) and not isinstance(exc, ModelProviderError):
                    raise
                error = normalize_provider_error(exc)
                if not self._should_retry(
                    error,
                    retry_count=retry_count,
                    messages=messages,
                    public_delta_emitted=False,
                ):
                    raise ModelProviderError(
                        error.normalized_error,
                        retryable=error.retryable,
                        retry_count=retry_count,
                    ) from None
                retry_count += 1

    def complete_stream(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        media_inputs: tuple[ModelMediaInput, ...] = (),
        on_text_delta: Callable[[ModelTextDelta], None],
        invocation_policy: ModelInvocationPolicy | None = None,
        strict_tools: bool = False,
    ) -> ModelCompletion:
        self._validate_strict_mode(tools, strict_tools=strict_tools)
        tool_names = provider_tool_names(tools)
        resolved = self._resolve_deepseek(invocation_policy, has_tools=bool(tools))
        request_body, request_metadata = self._request_body(
            messages,
            tools=tools,
            media_inputs=media_inputs,
            tool_names=tool_names,
            stream=True,
            resolved=resolved,
            strict_tools=strict_tools,
        )
        client = self._client or httpx.Client(timeout=self._client_timeout())
        should_close = self._client is None
        started = perf_counter()
        retry_count = 0
        public_delta_emitted = False

        def emit(delta: ModelTextDelta) -> None:
            nonlocal public_delta_emitted
            public_delta_emitted = True
            on_text_delta(delta)

        try:
            while True:
                try:
                    response_data = read_openai_stream(
                        client,
                        url=f"{self._base_url}{CHAT_COMPLETIONS_PATH}",
                        headers=self._headers(),
                        body=request_body,
                        on_text_delta=emit,
                    )
                    return parse_completion(
                        response_data,
                        provider_name=self._provider_name,
                        default_model_name=self._model_name,
                        latency_ms=int((perf_counter() - started) * 1000),
                        retry_count=retry_count,
                        resolved=resolved,
                        request_metadata=request_metadata,
                        internal_names=internal_tool_names(tools, tool_names),
                    )
                except Exception as exc:
                    if isinstance(exc, ModelResponseRejectedError):
                        raise
                    if isinstance(exc, ValueError) and not isinstance(exc, ModelProviderError):
                        raise
                    error = normalize_provider_error(exc)
                    if not self._should_retry(
                        error,
                        retry_count=retry_count,
                        messages=messages,
                        public_delta_emitted=public_delta_emitted,
                    ):
                        raise ModelProviderError(
                            error.normalized_error,
                            retryable=error.retryable,
                            retry_count=retry_count,
                        ) from None
                    retry_count += 1
        finally:
            if should_close:
                client.close()

    def _resolve_deepseek(
        self,
        policy: ModelInvocationPolicy | None,
        *,
        has_tools: bool,
    ) -> ResolvedDeepSeekInvocation | None:
        if self._deepseek_router is None:
            return None
        return self._deepseek_router.resolve(
            policy or ModelInvocationPolicy(),
            has_tools=has_tools,
        )

    def _request_body(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...],
        media_inputs: tuple[ModelMediaInput, ...],
        tool_names: tuple[str, ...],
        stream: bool,
        resolved: ResolvedDeepSeekInvocation | None,
        strict_tools: bool,
    ) -> tuple[dict[str, Any], ModelRequestMetadata | None]:
        self._media_capabilities.validate_request(
            media_inputs,
            has_tools=bool(tools),
            streaming=stream,
        )
        serialized_messages = [serialize_message(message) for message in messages]
        if media_inputs:
            self._add_media_parts(messages, serialized_messages, media_inputs)
        body: dict[str, Any] = {
            "model": resolved.profile.model if resolved else self._model_name,
            "messages": serialized_messages,
            "stream": stream,
        }
        if tools:
            serialized_tools = [
                serialize_tool(tool, provider_name=provider_name, strict=strict_tools)
                for tool, provider_name in zip(tools, tool_names, strict=True)
            ]
            if resolved is not None:
                serialized_tools.sort(key=_serialized_tool_name)
            body["tools"] = serialized_tools
        if resolved is not None:
            body.update(
                {
                    "thinking": {"type": resolved.thinking_mode.value},
                    "max_tokens": resolved.max_output_tokens,
                }
            )
            if resolved.thinking_mode is not ModelThinkingMode.ENABLED:
                body["tool_choice"] = resolved.tool_choice.value
            if resolved.reasoning_effort is not None:
                body["reasoning_effort"] = resolved.reasoning_effort.value
            if stream:
                body["stream_options"] = {"include_usage": True}
        elif self._provider_name.lower() == "qwen":
            body.update(
                {
                    "enable_thinking": self._model_thinking_mode
                    is ModelThinkingMode.ENABLED,
                    "enable_search": False,
                    "enable_code_interpreter": False,
                }
            )
            if stream:
                body["stream_options"] = {"include_usage": True}
        metadata = build_request_metadata(body, resolved) if resolved else None
        return body, metadata

    def _add_media_parts(
        self,
        messages: list[SessionMessage],
        serialized_messages: list[dict[str, object]],
        media_inputs: tuple[ModelMediaInput, ...],
    ) -> None:
        if self._media_resolver is None:
            raise ModelMediaUnsupportedError("model media resolver is unavailable")
        if len(messages) != len(serialized_messages):
            raise ModelMediaUnsupportedError("model media message serialization is inconsistent")
        source_user_indexes: dict[EventId, int] = {}
        for index, message in enumerate(messages):
            if message.role is not MessageRole.USER:
                continue
            for source_message_id in model_media_source_event_ids(message.metadata):
                if source_message_id in source_user_indexes:
                    raise ModelMediaUnsupportedError(
                        "model media source user message is ambiguous"
                    )
                source_user_indexes[source_message_id] = index
        media_by_user_index: dict[int, list[ModelMediaInput]] = {}
        for media in ordered_media_inputs(media_inputs):
            try:
                user_index = source_user_indexes[media.source_message_id]
            except KeyError as exc:
                raise ModelMediaUnsupportedError(
                    "model media source user message is missing from the request"
                ) from exc
            media_by_user_index.setdefault(user_index, []).append(media)
        for user_index, user_media in media_by_user_index.items():
            user_message = serialized_messages[user_index]
            content = user_message.get("content")
            if not isinstance(content, str):
                raise ModelMediaUnsupportedError("model media request user content is invalid")
            parts: list[dict[str, object]] = [{"type": "text", "text": content}]
            for media in user_media:
                payload = self._media_resolver.resolve_media(media)
                if len(payload) != media.size_bytes:
                    raise ModelMediaUnsupportedError(
                        "model media payload size does not match reference"
                    )
                if hashlib.sha256(payload).hexdigest() != media.sha256:
                    raise ModelMediaUnsupportedError(
                        "model media payload digest does not match reference"
                    )
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:{media.media_type};base64,"
                                f"{base64.b64encode(payload).decode('ascii')}"
                            )
                        },
                    }
                )
            user_message["content"] = parts

    def _validate_strict_mode(
        self,
        tools: tuple[ModelToolDefinition, ...],
        *,
        strict_tools: bool,
    ) -> None:
        if not strict_tools:
            return
        if self._deepseek_router is None or not self._base_url.endswith("/beta"):
            raise ValueError("DeepSeek strict tools require the isolated beta endpoint")
        if not tools:
            raise ValueError("DeepSeek strict tools require advertised tools")
        validate_strict_tools(tools)

    def _should_retry(
        self,
        error: ModelProviderError,
        *,
        retry_count: int,
        messages: list[SessionMessage],
        public_delta_emitted: bool,
    ) -> bool:
        return (
            self._deepseek_router is not None
            and error.retryable
            and retry_count < self._max_retries
            and not public_delta_emitted
            and not any(message.role is MessageRole.TOOL for message in messages)
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _client_timeout(self) -> float | httpx.Timeout:
        if self._deepseek_router is None:
            return self._timeout_s
        return httpx.Timeout(120.0, connect=10.0)

    def _post_chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self._client_timeout())
        should_close = self._client is None
        try:
            response = client.post(
                f"{self._base_url}{CHAT_COMPLETIONS_PATH}",
                headers=self._headers(),
                json=body,
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raw = response.content
                raise ModelResponseRejectedError(
                    "invalid_response_json",
                    phase="response_body",
                    retryable=True,
                    error_position=exc.pos,
                    payload_size=len(raw),
                    payload_sha256=hashlib.sha256(raw).hexdigest(),
                ) from exc
            if not isinstance(payload, dict):
                raw = response.content
                raise ModelResponseRejectedError(
                    "invalid_response_shape",
                    phase="response_body",
                    retryable=True,
                    payload_size=len(raw),
                    payload_sha256=hashlib.sha256(raw).hexdigest(),
                )
            return payload
        finally:
            if should_close:
                client.close()


def build_model_gateway(
    settings: ZebraAgentSettings,
    *,
    env: Mapping[str, str] | None = None,
    media_resolver: ModelMediaResolverPort | None = None,
    client: httpx.Client | None = None,
) -> OpenAICompatibleModelGateway:
    from agent_integrations.openai_gateway_factory import (
        build_model_gateway as build,
    )

    return build(settings, env=env, media_resolver=media_resolver, client=client)


def _serialized_tool_name(tool: dict[str, object]) -> str:
    function = tool.get("function")
    if not isinstance(function, dict):
        return ""
    name = function.get("name")
    return name if isinstance(name, str) else ""
