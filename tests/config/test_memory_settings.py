import pytest
from zebra_agent_config import load_settings


def test_memory_provider_defaults_to_explicitly_disabled() -> None:
    memory = load_settings(env={}).memory_gateway

    assert memory.provider == "disabled"
    assert memory.rollout == "off"
    assert memory.enabled is False


def test_redis_shadow_requires_complete_config_and_export_authority() -> None:
    base = {
        "ZEBRA_MEMORY_PROVIDER": "redis_agent_memory",
        "ZEBRA_MEMORY_ROLLOUT": "shadow",
    }
    with pytest.raises(ValueError, match="endpoint and Store ID"):
        load_settings(base)
    with pytest.raises(ValueError, match="data export authorization"):
        load_settings(
            {
                **base,
                "ZEBRA_REDIS_AGENT_MEMORY_ENDPOINT": "https://memory.example",
                "ZEBRA_REDIS_AGENT_MEMORY_STORE_ID": "store-a",
            }
        )

    memory = load_settings(
        {
            **base,
            "ZEBRA_REDIS_AGENT_MEMORY_ENDPOINT": "https://memory.example/",
            "ZEBRA_REDIS_AGENT_MEMORY_STORE_ID": "store-a",
            "ZEBRA_MEMORY_DATA_EXPORT_AUTHORIZED": "true",
            "ZEBRA_MEMORY_GENERATION": "2",
        }
    ).memory_gateway

    assert memory.enabled is True
    assert memory.endpoint == "https://memory.example"
    assert memory.generation == 2
    assert memory.api_key_env == "REDIS_AGENT_MEMORY_API_KEY"


def test_mem0_runtime_admission_remains_denied() -> None:
    with pytest.raises(ValueError, match="Mem0 runtime admission is denied"):
        load_settings(
            {
                "ZEBRA_MEMORY_PROVIDER": "mem0",
                "ZEBRA_MEMORY_ROLLOUT": "active",
            }
        )


def test_memory_rollout_rejects_implicit_provider_and_insecure_endpoint() -> None:
    with pytest.raises(ValueError, match="disabled Memory provider"):
        load_settings({"ZEBRA_MEMORY_ROLLOUT": "shadow"})
    with pytest.raises(ValueError, match="explicit insecure opt-in"):
        load_settings(
            {
                "ZEBRA_MEMORY_PROVIDER": "redis_agent_memory",
                "ZEBRA_MEMORY_ROLLOUT": "shadow",
                "ZEBRA_REDIS_AGENT_MEMORY_ENDPOINT": "http://memory.example",
                "ZEBRA_REDIS_AGENT_MEMORY_STORE_ID": "store-a",
                "ZEBRA_MEMORY_DATA_EXPORT_AUTHORIZED": "true",
            }
        )
