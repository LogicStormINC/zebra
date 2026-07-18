from dataclasses import dataclass
from typing import Literal

DeepSeekBetaCapability = Literal["strict_tools", "fim", "chat_prefix"]


@dataclass(frozen=True)
class DeepSeekBetaProfile:
    profile_id: str
    capability: DeepSeekBetaCapability
    model: str
    endpoint_path: str
    enabled_by_default: bool = False
    version_observed_at: str = "2026-07-17"


DEEPSEEK_BETA_PROFILES = (
    DeepSeekBetaProfile(
        profile_id="deepseek-v4-beta-strict-tools-v1",
        capability="strict_tools",
        model="deepseek-v4-flash",
        endpoint_path="/beta/chat/completions",
    ),
    DeepSeekBetaProfile(
        profile_id="deepseek-v4-pro-beta-fim-v1",
        capability="fim",
        model="deepseek-v4-pro",
        endpoint_path="/beta/completions",
    ),
    DeepSeekBetaProfile(
        profile_id="deepseek-v4-beta-chat-prefix-v1",
        capability="chat_prefix",
        model="deepseek-v4-flash",
        endpoint_path="/beta/chat/completions",
    ),
)

DEEPSEEK_BETA_PROFILE_BY_CAPABILITY = {
    profile.capability: profile for profile in DEEPSEEK_BETA_PROFILES
}
