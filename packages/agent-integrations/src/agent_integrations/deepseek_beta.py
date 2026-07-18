from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelInvocationPolicy,
    ModelThinkingMode,
    ModelToolDefinition,
)
from zebra_agent_config import ZebraAgentSettings

from agent_integrations.deepseek_beta_results import (
    DeepSeekBetaTextResult,
    EndpointVariant,
    beta_profile_id,
    fallback_beta_text_result,
    parse_beta_text_result,
)
from agent_integrations.model_errors import (
    ModelProviderError,
    normalize_provider_error,
)
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_integrations.openai_payloads import serialize_message


@dataclass(frozen=True)
class DeepSeekStrictToolResult:
    completion: ModelCompletion
    endpoint_variant: EndpointVariant
    profile_id: str
    fallback_reason: str | None = None


class DeepSeekBetaGateway:
    """Explicit, non-default access to DeepSeek's isolated beta protocol."""

    def __init__(
        self,
        *,
        stable_base_url: str,
        beta_base_url: str,
        api_key: str,
        model_name: str,
        client: httpx.Client | None = None,
    ) -> None:
        stable = stable_base_url.rstrip("/")
        beta = beta_base_url.rstrip("/")
        if stable.endswith("/beta"):
            raise ValueError("DeepSeek stable endpoint must not use /beta")
        if not beta.endswith("/beta") or beta == stable:
            raise ValueError("DeepSeek beta endpoint must be isolated under /beta")
        if not api_key.strip():
            raise ValueError("DeepSeek beta gateway requires an API key")
        self._stable_base_url = stable
        self._beta_base_url = beta
        self._api_key = api_key
        self._model_name = model_name
        self._client = client

    def complete_strict_tools(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...],
        invocation_policy: ModelInvocationPolicy | None = None,
        allow_stable_fallback: bool = True,
    ) -> DeepSeekStrictToolResult:
        beta = self._chat_gateway(self._beta_base_url)
        try:
            completion = beta.complete(
                messages,
                tools=tools,
                invocation_policy=invocation_policy,
                strict_tools=True,
            )
            return DeepSeekStrictToolResult(
                completion=completion,
                endpoint_variant="beta",
                profile_id=beta_profile_id("strict_tools"),
            )
        except ModelProviderError as exc:
            if not allow_stable_fallback or not _can_fallback(exc):
                raise
            completion = self._chat_gateway(self._stable_base_url).complete(
                messages,
                tools=tools,
                invocation_policy=invocation_policy,
            )
            return DeepSeekStrictToolResult(
                completion=completion,
                endpoint_variant="stable_fallback",
                profile_id=beta_profile_id("strict_tools"),
                fallback_reason=exc.normalized_error,
            )

    def complete_fim(
        self,
        prefix: str,
        *,
        suffix: str = "",
        max_tokens: int = 256,
        allow_stable_fallback: bool = True,
    ) -> DeepSeekBetaTextResult:
        if not prefix:
            raise ValueError("DeepSeek FIM prefix must not be empty")
        if max_tokens <= 0 or max_tokens > 4096:
            raise ValueError("DeepSeek FIM max_tokens must be between 1 and 4096")
        body: dict[str, object] = {
            "model": "deepseek-v4-pro",
            "prompt": prefix,
            "suffix": suffix,
            "max_tokens": max_tokens,
        }
        try:
            payload = self._post_beta("/completions", body)
            return parse_beta_text_result(payload, capability="fim")
        except ModelProviderError as exc:
            if not allow_stable_fallback or not _can_fallback(exc):
                raise
            instruction = (
                "Fill only the missing text between the exact prefix and suffix. "
                f"PREFIX:\n{prefix}\nSUFFIX:\n{suffix}"
            )
            completion = self._stable_text_completion(instruction, max_tokens=max_tokens)
            return fallback_beta_text_result(
                completion,
                capability="fim",
                reason=exc.normalized_error,
            )

    def complete_chat_prefix(
        self,
        messages: list[SessionMessage],
        *,
        prefix: str,
        max_tokens: int = 256,
        stop: tuple[str, ...] = (),
        allow_stable_fallback: bool = True,
    ) -> DeepSeekBetaTextResult:
        if not prefix:
            raise ValueError("DeepSeek chat prefix must not be empty")
        if max_tokens <= 0:
            raise ValueError("DeepSeek chat prefix max_tokens must be positive")
        body: dict[str, object] = {
            "model": self._model_name,
            "messages": [
                *(serialize_message(message) for message in messages),
                {"role": "assistant", "content": prefix, "prefix": True},
            ],
            "thinking": {"type": ModelThinkingMode.DISABLED.value},
            "max_tokens": max_tokens,
        }
        if stop:
            body["stop"] = list(stop)
        try:
            payload = self._post_beta("/chat/completions", body)
            result = parse_beta_text_result(payload, capability="chat_prefix")
            return DeepSeekBetaTextResult(
                capability=result.capability,
                text=f"{prefix}{result.text}",
                model_name=result.model_name,
                finish_reason=result.finish_reason,
                usage=result.usage,
                endpoint_variant=result.endpoint_variant,
                profile_id=result.profile_id,
            )
        except ModelProviderError as exc:
            if not allow_stable_fallback or not _can_fallback(exc):
                raise
            instruction = f"Continue this exact assistant prefix without repeating it:\n{prefix}"
            completion = self._chat_gateway(self._stable_base_url).complete(
                [*messages, _user_message(instruction)],
                invocation_policy=ModelInvocationPolicy(
                    thinking_mode=ModelThinkingMode.DISABLED,
                    max_output_tokens=max_tokens,
                ),
            )
            result = fallback_beta_text_result(
                completion,
                capability="chat_prefix",
                reason=exc.normalized_error,
            )
            return DeepSeekBetaTextResult(
                capability=result.capability,
                text=f"{prefix}{result.text}",
                model_name=result.model_name,
                finish_reason=result.finish_reason,
                usage=result.usage,
                endpoint_variant=result.endpoint_variant,
                profile_id=result.profile_id,
                fallback_reason=result.fallback_reason,
            )

    def _stable_text_completion(self, instruction: str, *, max_tokens: int) -> ModelCompletion:
        return self._chat_gateway(self._stable_base_url).complete(
            [_user_message(instruction)],
            invocation_policy=ModelInvocationPolicy(
                thinking_mode=ModelThinkingMode.DISABLED,
                max_output_tokens=max_tokens,
            ),
        )

    def _chat_gateway(self, base_url: str) -> OpenAICompatibleModelGateway:
        return OpenAICompatibleModelGateway(
            provider_name="deepseek",
            base_url=base_url,
            api_key=self._api_key,
            model_name=self._model_name,
            max_retries=0,
            client=self._client,
        )

    def _post_beta(self, path: str, body: dict[str, object]) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))
        should_close = self._client is None
        try:
            response = client.post(
                f"{self._beta_base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("DeepSeek beta response must be a JSON object")
            return payload
        except Exception as exc:
            error = normalize_provider_error(exc)
            raise ModelProviderError(
                error.normalized_error,
                retryable=error.retryable,
                retry_count=0,
            ) from exc
        finally:
            if should_close:
                client.close()


def build_deepseek_beta_gateway(
    settings: ZebraAgentSettings,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> DeepSeekBetaGateway:
    if settings.model.provider.lower() != "deepseek":
        raise ValueError("DeepSeek beta gateway requires the DeepSeek provider")
    if not settings.model.deepseek_beta_enabled:
        raise ValueError("DeepSeek beta capabilities are disabled by configuration")
    values = dict(env or {})
    if env is None:
        values.update(_read_defaults(Path(".env")))
        values.update(_read_defaults(Path(".env.local")))
    api_key = values.get(settings.model.api_key_env)
    if api_key is None:
        import os

        api_key = os.environ.get(settings.model.api_key_env)
    if not (api_key or "").strip():
        raise ValueError(f"missing API key in environment variable {settings.model.api_key_env}")
    beta_base_url = settings.model.deepseek_beta_base_url or (
        f"{settings.model.base_url.rstrip('/')}/beta"
    )
    return DeepSeekBetaGateway(
        stable_base_url=settings.model.base_url,
        beta_base_url=beta_base_url,
        api_key=api_key or "",
        model_name=settings.model.model,
        client=client,
    )


def _user_message(content: str) -> SessionMessage:
    return SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.USER,
        content=content,
        created_at=datetime.now(UTC),
    )


def _can_fallback(error: ModelProviderError) -> bool:
    return error.normalized_error not in {"authentication_failed", "insufficient_balance"}


def _read_defaults(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    defaults: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", maxsplit=1)
            defaults[key.strip()] = value.strip()
    return defaults
