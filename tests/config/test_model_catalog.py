import json
from dataclasses import replace

import pytest
from agent_core.domain.model_media import ModelInputModality
from agent_integrations import build_model_gateway
from zebra_agent_config import load_settings, settings_for_model


def _catalog_payload() -> dict[str, object]:
    return {
        "default_id": "qwen-native",
        "models": [
            {
                "id": "qwen-native",
                "label": "Qwen native media",
                "available": True,
                "settings": {
                    "provider": "qwen",
                    "api_key_env": "DASHSCOPE_API_KEY",
                    "base_url": "https://dashscope.example.test/v1",
                    "model": "qwen3.7-flash",
                    "profile_id": "qwen-flash-alias-native-v1",
                },
            },
            {
                "id": "deepseek-text",
                "label": "DeepSeek text with MCP",
                "available": True,
                "settings": {
                    "provider": "deepseek",
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "base_url": "https://deepseek.example.test/v1",
                    "model": "deepseek-v4-flash",
                },
            },
        ],
    }


def _catalog_settings():
    return load_settings({"ZEBRA_MODEL_CATALOG_JSON": json.dumps(_catalog_payload())})


def test_default_settings_expose_a_single_compatible_catalog_entry() -> None:
    catalog = load_settings({}).model_catalog

    assert catalog.default_id == "default"
    assert [entry.id for entry in catalog.entries] == ["default"]
    assert catalog.entries[0].settings.model == "deepseek-v4-flash"


def test_explicit_catalog_selects_independent_model_settings_and_gateways() -> None:
    settings = _catalog_settings()
    qwen_settings = settings_for_model(settings, "qwen-native")
    deepseek_settings = settings_for_model(settings, "deepseek-text")
    qwen = qwen_settings.model
    deepseek = deepseek_settings.model

    assert (qwen.provider, qwen.model, qwen.profile_id) == (
        "qwen",
        "qwen3.7-flash",
        "qwen-flash-alias-native-v1",
    )
    assert (deepseek.provider, deepseek.model) == ("deepseek", "deepseek-v4-flash")
    qwen_gateway = build_model_gateway(
        qwen_settings,
        env={"DASHSCOPE_API_KEY": "test-key"},
    )
    deepseek_gateway = build_model_gateway(
        deepseek_settings,
        env={"DEEPSEEK_API_KEY": "test-key"},
    )
    assert ModelInputModality.IMAGE in qwen_gateway.media_capabilities.input_modalities
    assert ModelInputModality.IMAGE not in deepseek_gateway.media_capabilities.input_modalities


def test_native_image_capability_requires_selected_profile_not_model_name() -> None:
    settings = _catalog_settings()
    qwen = settings.model_catalog.select("qwen-native").settings
    text_only_settings = replace(settings, model=replace(qwen, profile_id=None))

    gateway = build_model_gateway(text_only_settings, env={"DASHSCOPE_API_KEY": "test-key"})

    assert ModelInputModality.IMAGE not in gateway.media_capabilities.input_modalities


def test_unavailable_catalog_entry_fails_closed() -> None:
    payload = _catalog_payload()
    models = list(payload["models"])
    assert isinstance(models[1], dict)
    models[1] = {**models[1], "available": False}
    payload["models"] = models
    settings = load_settings({"ZEBRA_MODEL_CATALOG_JSON": json.dumps(payload)})

    with pytest.raises(ValueError, match="unavailable"):
        settings.model_catalog.select("deepseek-text")
