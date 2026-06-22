from pathlib import Path

from zebra_agent_config import load_settings


def test_load_settings_reads_default_profile() -> None:
    settings = load_settings(env={})

    assert settings.profile == "local"
    assert settings.database_url == ".zebra-agent/sessions.sqlite"
    assert settings.api.auth_token is None
    assert settings.model.provider == "deepseek"
    assert settings.model.api_key_env == "DEEPSEEK_API_KEY"
    assert settings.model.base_url == "https://api.deepseek.com"
    assert settings.model.model == "deepseek-v4-flash"


def test_load_settings_allows_env_override(tmp_path: Path) -> None:
    defaults_path = tmp_path / "default.env"
    defaults_path.write_text("ZEBRA_PROFILE=local\n", encoding="utf-8")

    settings = load_settings(
        {
            "ZEBRA_PROFILE": "ci",
            "ZEBRA_DATABASE_URL": "ci.sqlite",
            "ZEBRA_API_AUTH_TOKEN": "test-token",
            "ZEBRA_MODEL_PROVIDER": "test-provider",
            "ZEBRA_MODEL_API_KEY_ENV": "TEST_API_KEY",
            "ZEBRA_MODEL_BASE_URL": "https://example.test",
            "ZEBRA_MODEL_NAME": "test-model",
        },
        defaults_path=defaults_path,
    )

    assert settings.profile == "ci"
    assert settings.database_url == "ci.sqlite"
    assert settings.api.auth_token == "test-token"
    assert settings.model.provider == "test-provider"
    assert settings.model.api_key_env == "TEST_API_KEY"
    assert settings.model.base_url == "https://example.test"
    assert settings.model.model == "test-model"
