import json
import os
import sys
from pathlib import Path

import pytest
from zebra_agent_config import load_settings, trusted_local_mode_enabled


def test_load_settings_reads_default_profile() -> None:
    settings = load_settings(env={})

    assert settings.profile == "local"
    assert settings.database_url == ".zebra-agent/sessions.sqlite"
    assert settings.api.auth_token is None
    assert settings.session_handoff.enabled is False
    assert settings.live_events.redis_url is None
    assert settings.live_events.stream_max_length == 1_000
    assert settings.live_events.key_prefix == "zebra:live:v1"
    assert settings.model.provider == "deepseek"
    assert settings.model.api_key_env == "DEEPSEEK_API_KEY"
    assert settings.model.base_url == "https://api.deepseek.com"
    assert settings.model.model == "deepseek-v4-flash"
    assert settings.model.wire_api == "chat_completions"
    assert settings.model.executor_profile == "deepseek-v4-flash-executor-v1"
    assert settings.model.planner_profile == "deepseek-v4-pro-planner-v1"
    assert settings.model.reviewer_profile == "deepseek-v4-pro-reviewer-v1"
    assert settings.model.max_retries == 1
    assert settings.model.deepseek_beta_enabled is False
    assert settings.model.deepseek_beta_base_url == "https://api.deepseek.com/beta"
    assert settings.scm.provider == "local-only"
    assert settings.scm.github_owner is None
    assert settings.scm.github_repo is None
    assert settings.scm.github_token_env is None
    assert settings.scm.github_api_base_url == "https://api.github.com"
    assert settings.scm.pull_request_dry_run is True
    assert settings.web_search_endpoint is None
    assert settings.skill_roots == ()
    assert settings.mcp_servers == ()
    assert trusted_local_mode_enabled(settings) is True


def test_load_settings_allows_env_override(tmp_path: Path) -> None:
    defaults_path = tmp_path / "default.env"
    defaults_path.write_text("ZEBRA_PROFILE=local\n", encoding="utf-8")
    (tmp_path / "skills").mkdir()

    settings = load_settings(
        {
            "ZEBRA_PROFILE": "ci",
            "ZEBRA_DATABASE_URL": "ci.sqlite",
            "ZEBRA_API_AUTH_TOKEN": "test-token",
            "ZEBRA_SESSION_HANDOFF_ENABLED": "true",
            "ZEBRA_LIVE_REDIS_URL": "redis://redis-live:6379/0",
            "ZEBRA_LIVE_STREAM_MAX_LENGTH": "250",
            "ZEBRA_LIVE_STREAM_KEY_PREFIX": "zebra:test:v1",
            "ZEBRA_MODEL_PROVIDER": "test-provider",
            "ZEBRA_MODEL_API_KEY_ENV": "TEST_API_KEY",
            "ZEBRA_MODEL_BASE_URL": "https://example.test",
            "ZEBRA_MODEL_NAME": "test-model",
            "ZEBRA_MODEL_MAX_RETRIES": "0",
            "ZEBRA_SCM_PROVIDER": "github",
            "ZEBRA_GITHUB_OWNER": "octo-org",
            "ZEBRA_GITHUB_REPO": "zebra-agent",
            "ZEBRA_GITHUB_TOKEN_ENV": "GITHUB_APP_TOKEN",
            "ZEBRA_GITHUB_API_BASE_URL": "https://github.example/api",
            "ZEBRA_SCM_PULL_REQUEST_DRY_RUN": "false",
            "ZEBRA_WEB_SEARCH_ENDPOINT": "https://search.example.com/search",
            "ZEBRA_SKILL_ROOTS": f"{tmp_path}{os.pathsep}{tmp_path / 'skills'}",
        },
        defaults_path=defaults_path,
    )

    assert settings.profile == "ci"
    assert trusted_local_mode_enabled(settings) is False
    assert settings.database_url == "ci.sqlite"
    assert settings.api.auth_token == "test-token"
    assert settings.session_handoff.enabled is True
    assert settings.live_events.redis_url == "redis://redis-live:6379/0"
    assert settings.live_events.stream_max_length == 250
    assert settings.live_events.key_prefix == "zebra:test:v1"
    assert settings.model.provider == "test-provider"
    assert settings.model.api_key_env == "TEST_API_KEY"
    assert settings.model.base_url == "https://example.test"
    assert settings.model.model == "test-model"
    assert settings.model.max_retries == 0
    assert settings.scm.provider == "github"
    assert settings.scm.github_owner == "octo-org"
    assert settings.scm.github_repo == "zebra-agent"
    assert settings.scm.github_token_env == "GITHUB_APP_TOKEN"
    assert settings.scm.github_api_base_url == "https://github.example/api"
    assert settings.scm.pull_request_dry_run is False
    assert settings.web_search_endpoint == "https://search.example.com/search"
    assert settings.skill_roots == (
        str(tmp_path.resolve()),
        str((tmp_path / "skills").resolve()),
    )


def test_load_settings_rejects_missing_or_duplicate_skill_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing path"):
        load_settings({"ZEBRA_SKILL_ROOTS": str(tmp_path / "missing")})

    with pytest.raises(ValueError, match="duplicate path"):
        load_settings({"ZEBRA_SKILL_ROOTS": f"{tmp_path}{os.pathsep}{tmp_path.resolve()}"})


def test_load_settings_rejects_negative_model_retries() -> None:
    with pytest.raises(ValueError, match="ZEBRA_MODEL_MAX_RETRIES"):
        load_settings({"ZEBRA_MODEL_MAX_RETRIES": "-1"})


def test_load_settings_accepts_explicit_deepseek_responses_wire() -> None:
    settings = load_settings({"ZEBRA_DEEPSEEK_WIRE_API": "responses"})

    assert settings.model.wire_api == "responses"


def test_load_settings_rejects_responses_for_other_providers() -> None:
    with pytest.raises(ValueError, match="requires provider=deepseek"):
        load_settings(
            {
                "ZEBRA_MODEL_PROVIDER": "custom",
                "ZEBRA_DEEPSEEK_WIRE_API": "responses",
            }
        )


def test_load_settings_parses_bounded_stdio_mcp_servers(tmp_path: Path) -> None:
    script = tmp_path / "server.py"
    script.write_text("pass", encoding="utf-8")
    settings = load_settings(
        {
            "ZEBRA_MCP_SERVERS": json.dumps(
                {"local": {"command": sys.executable, "args": [str(script)]}}
            )
        }
    )

    assert settings.mcp_servers[0].name == "local"
    assert settings.mcp_servers[0].command == str(Path(sys.executable).resolve())
    assert settings.mcp_servers[0].args == (str(script),)


@pytest.mark.parametrize(
    "payload, message",
    [
        ("[]", "JSON object"),
        (json.dumps({"Bad.Name": {"command": sys.executable}}), "server name"),
        (json.dumps({"x": {"command": "python"}}), "must be absolute"),
        (json.dumps({"x": {"command": "/missing/mcp"}}), "does not exist"),
        (
            json.dumps({"x": {"command": sys.executable, "args": ["-c", "pass"]}}),
            "inline Python",
        ),
    ],
)
def test_load_settings_rejects_unsafe_mcp_config(payload: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_settings({"ZEBRA_MCP_SERVERS": payload})


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


def test_load_settings_requires_pinned_image_for_hard_runtime() -> None:
    with pytest.raises(ValueError, match="pinned by sha256"):
        load_settings({"ZEBRA_RUNTIME_CLASS": "gvisor", "ZEBRA_RUNTIME_IMAGE": "latest"})

    settings = load_settings(
        {
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_CPUS": "1.5",
            "ZEBRA_RUNTIME_MEMORY_MB": "1024",
        }
    )

    assert settings.runtime.runtime_class == "gvisor"
    assert settings.runtime.cpu_count == 1.5
    assert settings.runtime.memory_mb == 1024


def test_load_settings_allows_os_sandbox_without_container_image() -> None:
    settings = load_settings({"ZEBRA_RUNTIME_CLASS": "os-sandbox"})

    assert settings.runtime.runtime_class == "os-sandbox"
    assert settings.runtime.image == ""


def test_load_settings_parses_explicit_setup_phase() -> None:
    digest = "a" * 64
    settings = load_settings(
        {
            "ZEBRA_SETUP_ENABLED": "true",
            "ZEBRA_SETUP_COMMAND_JSON": '["/bin/sh","-c","test -f package.whl"]',
            "ZEBRA_SETUP_ALLOWED_DOMAINS": "files.example.test",
            "ZEBRA_SETUP_DEPENDENCIES_JSON": json.dumps(
                [
                    {
                        "url": "https://files.example.test/package.whl",
                        "sha256": digest,
                        "file_name": "package.whl",
                    }
                ]
            ),
            "ZEBRA_SETUP_LOCKFILES": "uv.lock",
            "ZEBRA_SETUP_CREDENTIAL_ENV": "TEMP_SETUP_TOKEN",
        }
    )

    assert settings.setup.enabled is True
    assert settings.setup.command[0] == "/bin/sh"
    assert settings.setup.allowed_domains == ("files.example.test",)
    assert settings.setup.dependencies[0].sha256 == digest
    assert settings.setup.lockfiles == ("uv.lock",)
    assert settings.setup.credential_env == "TEMP_SETUP_TOKEN"


def test_load_settings_rejects_partial_or_implicit_setup_configuration() -> None:
    with pytest.raises(ValueError, match="requires ZEBRA_SETUP_ENABLED"):
        load_settings({"ZEBRA_SETUP_COMMAND_JSON": '["/bin/true"]'})
    with pytest.raises(ValueError, match="requires command"):
        load_settings({"ZEBRA_SETUP_ENABLED": "true"})


def test_production_profile_fails_closed_without_gvisor() -> None:
    with pytest.raises(ValueError, match="requires ZEBRA_RUNTIME_CLASS=gvisor"):
        load_settings({"ZEBRA_PROFILE": "production"})
    with pytest.raises(ValueError, match="pinned by sha256"):
        load_settings({"ZEBRA_PROFILE": "production", "ZEBRA_RUNTIME_CLASS": "gvisor"})
    with pytest.raises(ValueError, match="requires ZEBRA_RUNTIME_CLASS=gvisor"):
        load_settings(
            {
                "ZEBRA_PROFILE": "production",
                "ZEBRA_RUNTIME_CLASS": "trusted-local",
            }
        )
    image = "zebra/runtime@sha256:" + "a" * 64
    with pytest.raises(ValueError, match="storage-enforced workspace quota"):
        load_settings(
            {
                "ZEBRA_PROFILE": "production",
                "ZEBRA_RUNTIME_CLASS": "gvisor",
                "ZEBRA_RUNTIME_IMAGE": image,
                "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "false",
            }
        )


def test_load_settings_auto_loads_dotenv_local(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.local").write_text(
        "DEEPSEEK_API_KEY=local-secret\nDEEPSEEK_BASE_URL=https://local.deepseek.test\nDEEPSEEK_MODEL=local-model\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    settings = load_settings(env={})

    assert settings.model.base_url == "https://local.deepseek.test"
    assert settings.model.model == "local-model"
    assert settings.model.api_key_env == "DEEPSEEK_API_KEY"
