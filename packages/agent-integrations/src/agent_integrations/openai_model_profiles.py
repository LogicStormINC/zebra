from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from agent_core.domain.model_media import ModelInputModality, ModelMediaCapabilities
from agent_core.domain.modeling import ModelThinkingMode


@dataclass(frozen=True)
class ModelProfile:
    expected_provider: str
    expected_model: str
    media_capabilities: ModelMediaCapabilities
    thinking_mode: ModelThinkingMode = ModelThinkingMode.DISABLED


MODEL_PROFILES: Mapping[str, ModelProfile] = MappingProxyType(
    {
        "qwen-flash-native-v1": ModelProfile(
            expected_provider="qwen",
            expected_model="qwen3.7-flash-2026-07-15",
            media_capabilities=ModelMediaCapabilities(
                input_modalities=frozenset({ModelInputModality.TEXT, ModelInputModality.IMAGE}),
                supports_tools_with_media=True,
                supports_streaming_with_media=True,
                max_image_count=4,
                max_image_bytes=5 * 1024 * 1024,
                max_total_image_bytes=20 * 1024 * 1024,
                image_media_types=frozenset({"image/jpeg", "image/png"}),
            ),
        ),
        "qwen-flash-alias-native-v1": ModelProfile(
            expected_provider="qwen",
            expected_model="qwen3.7-flash",
            media_capabilities=ModelMediaCapabilities(
                input_modalities=frozenset({ModelInputModality.TEXT, ModelInputModality.IMAGE}),
                supports_tools_with_media=True,
                supports_streaming_with_media=True,
                max_image_count=4,
                max_image_bytes=5 * 1024 * 1024,
                max_total_image_bytes=20 * 1024 * 1024,
                image_media_types=frozenset({"image/jpeg", "image/png"}),
            ),
        ),
        "qwen-plus-native-v1": ModelProfile(
            expected_provider="qwen",
            expected_model="qwen3.7-plus",
            media_capabilities=ModelMediaCapabilities(
                input_modalities=frozenset({ModelInputModality.TEXT, ModelInputModality.IMAGE}),
                max_image_count=3,
                max_image_bytes=5 * 1024 * 1024,
                max_total_image_bytes=20 * 1024 * 1024,
                image_media_types=frozenset({"image/jpeg", "image/png"}),
            ),
        ),
        "qwen-max-text-v1": ModelProfile(
            expected_provider="qwen",
            expected_model="qwen3.7-max",
            media_capabilities=ModelMediaCapabilities(),
        ),
        "qwen-max-dated-thinking-v1": ModelProfile(
            expected_provider="qwen",
            expected_model="qwen3.7-max-2026-05-17",
            media_capabilities=ModelMediaCapabilities(),
            thinking_mode=ModelThinkingMode.ENABLED,
        ),
        "qwen-max-preview-thinking-v1": ModelProfile(
            expected_provider="qwen",
            expected_model="qwen3.7-max-preview",
            media_capabilities=ModelMediaCapabilities(),
            thinking_mode=ModelThinkingMode.ENABLED,
        ),
    }
)


def resolve_model_profile(
    profile_id: str | None,
    *,
    provider: str,
    model: str,
    profiles: Mapping[str, ModelProfile] = MODEL_PROFILES,
) -> ModelMediaCapabilities:
    if profile_id is None:
        return ModelMediaCapabilities()
    return _resolve_profile(profile_id, provider, model, profiles).media_capabilities


def resolve_model_thinking_mode(
    profile_id: str | None,
    *,
    provider: str,
    model: str,
    profiles: Mapping[str, ModelProfile] = MODEL_PROFILES,
) -> ModelThinkingMode:
    if profile_id is None:
        return ModelThinkingMode.DISABLED
    return _resolve_profile(profile_id, provider, model, profiles).thinking_mode


def _resolve_profile(
    profile_id: str,
    provider: str,
    model: str,
    profiles: Mapping[str, ModelProfile],
) -> ModelProfile:
    try:
        profile = profiles[profile_id]
    except KeyError:
        raise ValueError(f"unknown model profile: {profile_id}") from None
    if provider != profile.expected_provider:
        raise ValueError(f"model profile provider mismatch: {profile_id}")
    if model != profile.expected_model:
        raise ValueError(f"model profile model mismatch: {profile_id}")
    return profile
