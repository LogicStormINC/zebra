"""Provider selection and credential/settings composition for model gateways."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx
from agent_core.domain.modeling import ModelRole

from agent_integrations.deepseek_profiles import DeepSeekProfileRouter
from agent_integrations.deepseek_responses import DeepSeekResponsesModelGateway
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_integrations.provider_defaults import _read_defaults
from agent_integrations.provider_settings import ModelProviderSettings


def build_model_gateway(
    settings: ModelProviderSettings,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> OpenAICompatibleModelGateway | DeepSeekResponsesModelGateway:
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
    if settings.wire_api == "responses":
        if settings.provider.lower() != "deepseek":
            raise ValueError("Responses wire API is only supported for DeepSeek")
        return DeepSeekResponsesModelGateway(
            base_url=settings.base_url,
            api_key=normalized_key,
            model_name=settings.model,
            max_retries=settings.max_retries,
            deepseek_router=router,
            client=client,
        )
    if settings.wire_api != "chat_completions":
        raise ValueError(f"unsupported model wire API: {settings.wire_api}")
    return OpenAICompatibleModelGateway(
        provider_name=settings.provider,
        base_url=settings.base_url,
        api_key=normalized_key,
        model_name=settings.model,
        max_retries=settings.max_retries,
        deepseek_router=router,
        client=client,
    )
