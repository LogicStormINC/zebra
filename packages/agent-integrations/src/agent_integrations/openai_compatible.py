from __future__ import annotations

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
    ModelToolDefinition,
)
from zebra_agent_config import ZebraAgentSettings

from agent_integrations.deepseek_profiles import (
    DeepSeekProfileRouter,
    ResolvedDeepSeekInvocation,
)
from agent_integrations.model_errors import ModelProviderError, normalize_provider_error
from agent_integrations.openai_payloads import (
    internal_tool_names,
    parse_completion,
    provider_tool_names,
    serialize_message,
    serialize_tool,
)
from agent_integrations.openai_streaming import read_openai_stream

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
    ) -> ModelCompletion:
        tool_names = provider_tool_names(tools)
        resolved = self._resolve_deepseek(invocation_policy, has_tools=bool(tools))
        request_body = self._request_body(
            messages,
            tools=tools,
            tool_names=tool_names,
            stream=False,
            resolved=resolved,
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
                    internal_names=internal_tool_names(tools, tool_names),
                )
            except Exception as exc:
                if self._deepseek_router is None:
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
    ) -> ModelCompletion:
        tool_names = provider_tool_names(tools)
        resolved = self._resolve_deepseek(invocation_policy, has_tools=bool(tools))
        request_body = self._request_body(
            messages,
            tools=tools,
            tool_names=tool_names,
            stream=True,
            resolved=resolved,
        )
        client = self._client or httpx.Client(timeout=self._timeout_s)
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
                        internal_names=internal_tool_names(tools, tool_names),
                    )
                except Exception as exc:
                    if self._deepseek_router is None:
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
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": resolved.profile.model if resolved else self._model_name,
            "messages": [serialize_message(message) for message in messages],
            "stream": stream,
        }
        if tools:
            body["tools"] = [
                serialize_tool(tool, provider_name=provider_name)
                for tool, provider_name in zip(tools, tool_names, strict=True)
            ]
        if resolved is not None:
            body.update(
                {
                    "thinking": {"type": resolved.thinking_mode.value},
                    "tool_choice": resolved.tool_choice.value,
                    "max_tokens": resolved.max_output_tokens,
                }
            )
            if resolved.reasoning_effort is not None:
                body["reasoning_effort"] = resolved.reasoning_effort.value
            if stream:
                body["stream_options"] = {"include_usage": True}
        return body

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

    def _post_chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self._timeout_s)
        should_close = self._client is None
        try:
            response = client.post(
                f"{self._base_url}{CHAT_COMPLETIONS_PATH}",
                headers=self._headers(),
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("model gateway response must be a JSON object")
            return payload
        finally:
            if should_close:
                client.close()


def build_model_gateway(
    settings: ZebraAgentSettings,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> OpenAICompatibleModelGateway:
    values = dict(env or {})
    if env is None:
        values.update(_read_defaults(Path(".env")))
        values.update(_read_defaults(Path(".env.local")))
    api_key = values.get(settings.model.api_key_env)
    if api_key is None:
        import os

        api_key = os.environ.get(settings.model.api_key_env)
    normalized_key = (api_key or "").strip()
    if not normalized_key:
        raise ValueError(f"missing API key in environment variable {settings.model.api_key_env}")
    router = None
    if settings.model.provider.lower() == "deepseek":
        configured_profiles = {
            role: profile_id
            for role, profile_id in (
                (ModelRole.EXECUTOR, settings.model.executor_profile),
                (ModelRole.PLANNER, settings.model.planner_profile),
                (ModelRole.REVIEWER, settings.model.reviewer_profile),
                (ModelRole.SUMMARIZER, settings.model.summarizer_profile),
                (ModelRole.ANALYST, settings.model.analyst_profile),
                (ModelRole.CLASSIFIER, settings.model.classifier_profile),
            )
            if profile_id is not None
        }
        router = DeepSeekProfileRouter(
            role_profiles=configured_profiles,
            legacy_executor_model=settings.model.model,
        )
    return OpenAICompatibleModelGateway(
        provider_name=settings.model.provider,
        base_url=settings.model.base_url,
        api_key=normalized_key,
        model_name=settings.model.model,
        max_retries=settings.model.max_retries,
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
