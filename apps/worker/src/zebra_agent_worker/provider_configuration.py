from __future__ import annotations

from agent_integrations import ModelProviderSettings
from zebra_agent_config import ZebraAgentSettings


def model_provider_settings(settings: ZebraAgentSettings) -> ModelProviderSettings:
    model = settings.model
    return ModelProviderSettings(
        provider=model.provider,
        api_key_env=model.api_key_env,
        base_url=model.base_url,
        model=model.model,
        executor_profile=model.executor_profile,
        planner_profile=model.planner_profile,
        reviewer_profile=model.reviewer_profile,
        summarizer_profile=model.summarizer_profile,
        analyst_profile=model.analyst_profile,
        classifier_profile=model.classifier_profile,
        max_retries=model.max_retries,
        deepseek_beta_enabled=model.deepseek_beta_enabled,
        deepseek_beta_base_url=model.deepseek_beta_base_url,
    )
