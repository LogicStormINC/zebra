from pathlib import Path

import pytest
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
    assert settings.scm.provider == "local-only"
    assert settings.scm.github_owner is None
    assert settings.scm.github_repo is None
    assert settings.scm.github_token_env is None
    assert settings.scm.github_api_base_url == "https://api.github.com"
    assert settings.scm.pull_request_dry_run is True


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
            "ZEBRA_SCM_PROVIDER": "github",
            "ZEBRA_GITHUB_OWNER": "octo-org",
            "ZEBRA_GITHUB_REPO": "zebra-agent",
            "ZEBRA_GITHUB_TOKEN_ENV": "GITHUB_APP_TOKEN",
            "ZEBRA_GITHUB_API_BASE_URL": "https://github.example/api",
            "ZEBRA_SCM_PULL_REQUEST_DRY_RUN": "false",
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
    assert settings.scm.provider == "github"
    assert settings.scm.github_owner == "octo-org"
    assert settings.scm.github_repo == "zebra-agent"
    assert settings.scm.github_token_env == "GITHUB_APP_TOKEN"
    assert settings.scm.github_api_base_url == "https://github.example/api"
    assert settings.scm.pull_request_dry_run is False


def test_load_settings_rejects_github_provider_without_token_env() -> None:
    with pytest.raises(ValueError, match="ZEBRA_GITHUB_TOKEN_ENV"):
        load_settings(
            {
                "ZEBRA_SCM_PROVIDER": "github",
                "ZEBRA_GITHUB_OWNER": "octo-org",
                "ZEBRA_GITHUB_REPO": "zebra-agent",
            }
        )


def test_load_settings_reads_scm_defaults_file(tmp_path: Path) -> None:
    defaults_path = tmp_path / "default.env"
    defaults_path.write_text(
        "\n".join(
            [
                "ZEBRA_SCM_PROVIDER=github",
                "ZEBRA_GITHUB_OWNER=default-org",
                "ZEBRA_GITHUB_REPO=default-repo",
                "ZEBRA_GITHUB_TOKEN_ENV=DEFAULT_GITHUB_TOKEN",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env={}, defaults_path=defaults_path)

    assert settings.scm.provider == "github"
    assert settings.scm.github_owner == "default-org"
    assert settings.scm.github_repo == "default-repo"
    assert settings.scm.github_token_env == "DEFAULT_GITHUB_TOKEN"


def test_load_settings_does_not_store_scm_token_value() -> None:
    settings = load_settings(
        {
            "ZEBRA_SCM_PROVIDER": "github",
            "ZEBRA_GITHUB_OWNER": "octo-org",
            "ZEBRA_GITHUB_REPO": "zebra-agent",
            "ZEBRA_GITHUB_TOKEN_ENV": "GITHUB_TOKEN",
            "GITHUB_TOKEN": "secret-token",
        }
    )

    assert settings.scm.github_token_env == "GITHUB_TOKEN"
    assert "secret-token" not in repr(settings.scm)
