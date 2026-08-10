from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelInvocationPolicy,
    ModelRole,
    ModelTextDelta,
    ModelThinkingMode,
    ModelToolDefinition,
)
from agent_core.ports.model_gateway import ModelResponseRejectedError

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
from agent_integrations.provider_settings import ModelProviderSettings
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
        client: httpx.Client | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._deepseek_router = deepseek_router
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

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        invocation_policy: ModelInvocationPolicy | None = None,
        strict_tools: bool = False,
    ) -> ModelCompletion:
        self._validate_strict_mode(tools, strict_tools=strict_tools)
        tool_names = provider_tool_names(tools)
        resolved = self._resolve_deepseek(invocation_policy, has_tools=bool(tools))
        request_body, request_metadata = self._request_body(
            messages,
            tools=tools,
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
                    ) from exc
                retry_count += 1

    def complete_stream(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
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
                        ) from exc
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
        tool_names: tuple[str, ...],
        stream: bool,
        resolved: ResolvedDeepSeekInvocation | None,
        strict_tools: bool,
    ) -> tuple[dict[str, Any], ModelRequestMetadata | None]:
        body: dict[str, Any] = {
            "model": resolved.profile.model if resolved else self._model_name,
            "messages": [serialize_message(message) for message in messages],
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
        metadata = build_request_metadata(body, resolved) if resolved else None
        return body, metadata

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
    settings: ModelProviderSettings,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> OpenAICompatibleModelGateway:
    values = dict(env or {})
    if env is None:
        values.update(_read_defaults(Path(".env")))
        values.update(_read_defaults(Path(".env.local")))
    api_key = values.get(settings.api_key_env)
    if api_key is None:
        import os

        api_key = os.environ.get(settings.api_key_env)
    normalized_key = (api_key or "").strip()
    if not normalized_key:
        raise ValueError(f"missing API key in environment variable {settings.api_key_env}")
    router = None
    if settings.provider.lower() == "deepseek":
        configured_profiles = {
            role: profile_id
            for role, profile_id in (
                (ModelRole.EXECUTOR, settings.executor_profile),
                (ModelRole.PLANNER, settings.planner_profile),
                (ModelRole.REVIEWER, settings.reviewer_profile),
                (ModelRole.SUMMARIZER, settings.summarizer_profile),
                (ModelRole.ANALYST, settings.analyst_profile),
                (ModelRole.CLASSIFIER, settings.classifier_profile),
            )
            if profile_id is not None
        }
        router = DeepSeekProfileRouter(
            role_profiles=configured_profiles,
            legacy_executor_model=settings.model,
        )
    return OpenAICompatibleModelGateway(
        provider_name=settings.provider,
        base_url=settings.base_url,
        api_key=normalized_key,
        model_name=settings.model,
        max_retries=settings.max_retries,
        deepseek_router=router,
        client=client,
    )


def _read_defaults(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    defaults: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        defaults[key.strip()] = value.strip()
    return defaults


def _serialized_tool_name(tool: dict[str, object]) -> str:
    function = tool.get("function")
    if not isinstance(function, dict):
        return ""
    name = function.get("name")
    return name if isinstance(name, str) else ""
