from __future__ import annotations

import hashlib
from collections.abc import Callable
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelInvocationPolicy,
    ModelTextDelta,
    ModelThinkingMode,
    ModelToolDefinition,
)
from agent_core.ports.model_gateway import ModelResponseRejectedError

from agent_integrations.bounded_model_http import post_bounded_json, validate_bounded_policy
from agent_integrations.deepseek_profiles import (
    DeepSeekProfileRouter,
    ResolvedDeepSeekInvocation,
)
from agent_integrations.deepseek_responses_parse import (
    parse_responses_completion as parse_responses_completion,
)
from agent_integrations.deepseek_responses_payloads import (
    request_metadata,
    serialize_input,
)
from agent_integrations.deepseek_responses_streaming import (
    read_deepseek_responses_stream,
)
from agent_integrations.model_errors import (
    ModelProviderError,
    log_provider_attempt,
    normalize_provider_error,
)
from agent_integrations.openai_payloads import (
    internal_tool_names,
    provider_tool_names,
)
from agent_integrations.request_metadata import ModelRequestMetadata

RESPONSES_PATH = "/responses"


class DeepSeekResponsesModelGateway:
    """DeepSeek's stateless Responses adapter, including native image inputs."""

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
        self._router = deepseek_router or DeepSeekProfileRouter(legacy_executor_model=model_name)
        self._client = client
        self.authority_check: Callable[[str], None] | None = None

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
        deadline_s: float | None = None,
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
        call_id = uuid4().hex
        if deadline_s is not None:
            validate_bounded_policy(invocation_policy, has_tools=bool(tools))
        retries = 0
        while True:
            if self.authority_check is not None:
                self.authority_check(call_id)
            attempt_started = perf_counter()
            try:
                payload = self._post(body, deadline_s=deadline_s)
                completion = parse_responses_completion(
                    payload,
                    resolved=resolved,
                    request_metadata=metadata,
                    internal_names=internal_tool_names(tools, names),
                    tools_advertised=bool(tools),
                    latency_ms=int((perf_counter() - started) * 1000),
                    retry_count=retries,
                )
                log_provider_attempt(
                    call_id, retries + 1, started, attempt_started, completion=completion
                )
                return completion
            except Exception as exc:
                log_provider_attempt(call_id, retries + 1, started, attempt_started, error=exc)
                if deadline_s is not None:
                    if isinstance(exc, ModelResponseRejectedError):
                        exc.retryable = False
                    if isinstance(exc, ValueError | ModelResponseRejectedError):
                        raise
                    error = normalize_provider_error(exc)
                    raise ModelProviderError(
                        error.normalized_error, retryable=False, retry_count=0
                    ) from exc
                retries = self._retry_or_raise(
                    exc,
                    retries=retries,
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
        call_id = uuid4().hex
        retries = 0
        public_delta_emitted = False

        def mark_semantic_output() -> None:
            nonlocal public_delta_emitted
            public_delta_emitted = True

        try:
            while True:
                if self.authority_check is not None:
                    self.authority_check(call_id)
                attempt_started = perf_counter()
                try:
                    payload = read_deepseek_responses_stream(
                        client,
                        url=f"{self._base_url}{RESPONSES_PATH}",
                        headers=self._headers(),
                        body=body,
                        on_text_delta=on_text_delta,
                        on_semantic_output=mark_semantic_output,
                    )
                    # Completed private output is safe for bounded Harness parse repair.
                    public_delta_emitted = (
                        payload.get("_zebra_time_to_first_public_text_ms") is not None
                    )
                    completion = parse_responses_completion(
                        payload,
                        resolved=resolved,
                        request_metadata=metadata,
                        internal_names=internal_tool_names(tools, names),
                        tools_advertised=bool(tools),
                        latency_ms=int((perf_counter() - started) * 1000),
                        retry_count=retries,
                    )
                    log_provider_attempt(
                        call_id, retries + 1, started, attempt_started, completion=completion
                    )
                    return completion
                except Exception as exc:
                    log_provider_attempt(call_id, retries + 1, started, attempt_started, error=exc)
                    retries = self._retry_or_raise(
                        exc,
                        retries=retries,
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
        if resolved.profile.model not in {
            "deepseek-flash",
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
            "deepseek-v4-pro",
        }:
            raise ValueError("DeepSeek Responses requires a supported model profile")
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

    def _post(self, body: dict[str, Any], *, deadline_s: float | None = None) -> dict[str, Any]:
        if deadline_s is not None:
            return post_bounded_json(
                self._client,
                f"{self._base_url}{RESPONSES_PATH}",
                self._headers(),
                body,
                deadline_s=deadline_s,
            )
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
        public_delta_emitted: bool,
    ) -> int:
        if isinstance(exc, ModelResponseRejectedError):
            if public_delta_emitted or retries:
                exc.retryable = False
            raise exc
        if isinstance(exc, ValueError) and not isinstance(exc, ModelProviderError):
            raise exc
        error = normalize_provider_error(exc)
        if error.retryable and retries < self._max_retries and not public_delta_emitted:
            return retries + 1
        raise ModelProviderError(
            error.normalized_error,
            retryable=False,
            retry_count=retries,
        ) from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
