from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    api_key_env: str
    base_url: str
    model: str
    wire_api: str = "chat_completions"
    executor_profile: str | None = None
    planner_profile: str | None = None
    reviewer_profile: str | None = None
    summarizer_profile: str | None = None
    analyst_profile: str | None = None
    classifier_profile: str | None = None
    max_retries: int = 1
    deepseek_beta_enabled: bool = False
    deepseek_beta_base_url: str | None = None
