import os
from collections.abc import Mapping
from pathlib import Path

import httpx
from agent_core.domain.modeling import ModelRole
from agent_core.ports.model_gateway import ModelMediaResolverPort
from zebra_agent_config import ZebraAgentSettings

from agent_integrations.deepseek_profiles import DeepSeekProfileRouter
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_integrations.openai_model_profiles import (
    resolve_model_profile,
    resolve_model_thinking_mode,
)


def build_model_gateway(
    settings: ZebraAgentSettings,
    *,
    env: Mapping[str, str] | None = None,
    media_resolver: ModelMediaResolverPort | None = None,
    client: httpx.Client | None = None,
) -> OpenAICompatibleModelGateway:
    media_capabilities = resolve_model_profile(
        settings.model.profile_id,
        provider=settings.model.provider,
        model=settings.model.model,
    )
    values = dict(env or {})
    if env is None:
        values.update(_read_defaults(Path(".env")))
        values.update(_read_defaults(Path(".env.local")))
    api_key = values.get(settings.model.api_key_env) or os.environ.get(
        settings.model.api_key_env
    )
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
        media_capabilities=media_capabilities,
        model_thinking_mode=resolve_model_thinking_mode(
            settings.model.profile_id,
            provider=settings.model.provider,
            model=settings.model.model,
        ),
        media_resolver=media_resolver,
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
