from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agent_core.domain.modeling import ModelCompletion, ModelUsage

from agent_integrations.deepseek_beta_profiles import (
    DEEPSEEK_BETA_PROFILE_BY_CAPABILITY,
    DeepSeekBetaCapability,
)
from agent_integrations.model_errors import finish_reason_error
from agent_integrations.openai_payloads import optional_str, parse_usage

EndpointVariant = Literal["beta", "stable_fallback"]
TextCapability = Literal["fim", "chat_prefix"]


@dataclass(frozen=True)
class DeepSeekBetaTextResult:
    capability: TextCapability
    text: str
    model_name: str
    finish_reason: str | None
    usage: ModelUsage
    endpoint_variant: EndpointVariant
    profile_id: str
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("DeepSeek beta completion text must not be empty")


def parse_beta_text_result(
    payload: dict[str, Any],
    *,
    capability: TextCapability,
) -> DeepSeekBetaTextResult:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("DeepSeek beta response must include a choice")
    choice = choices[0]
    finish_reason = optional_str(choice.get("finish_reason"))
    finish_error = finish_reason_error(finish_reason)
    if finish_error is not None:
        raise finish_error
    if capability == "fim":
        text = choice.get("text")
    else:
        message = choice.get("message")
        text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text:
        raise ValueError("DeepSeek beta response text must not be empty")
    return DeepSeekBetaTextResult(
        capability=capability,
        text=text,
        model_name=optional_str(payload.get("model")) or "unknown",
        finish_reason=finish_reason,
        usage=parse_usage(payload.get("usage")),
        endpoint_variant="beta",
        profile_id=beta_profile_id(capability),
    )


def fallback_beta_text_result(
    completion: ModelCompletion,
    *,
    capability: TextCapability,
    reason: str,
) -> DeepSeekBetaTextResult:
    return DeepSeekBetaTextResult(
        capability=capability,
        text=completion.assistant_message.content,
        model_name=completion.call_metadata.resolved_model or "unknown",
        finish_reason=completion.call_metadata.finish_reason,
        usage=completion.call_metadata.usage,
        endpoint_variant="stable_fallback",
        profile_id=beta_profile_id(capability),
        fallback_reason=reason,
    )


def beta_profile_id(capability: DeepSeekBetaCapability) -> str:
    return DEEPSEEK_BETA_PROFILE_BY_CAPABILITY[capability].profile_id
