from agent_security import REDACTED_SECRET, ScmCredentialBoundary
from zebra_agent_config import ScmSettings


def test_scm_credential_boundary_uses_no_token_for_local_only() -> None:
    capability = ScmCredentialBoundary().capability_from_settings(_local_scm())

    assert capability.provider == "local-only"
    assert capability.token_env is None
    assert capability.token_value is None
    assert capability.redacted() == {
        "provider": "local-only",
        "token_env": None,
        "token_value": None,
    }


def test_scm_credential_boundary_keeps_token_env_and_redacts_value() -> None:
    capability = ScmCredentialBoundary().capability_from_settings(
        _github_scm(),
        token_value="secret-token",
    )

    assert capability.provider == "github"
    assert capability.token_env == "GITHUB_TOKEN"
    assert capability.token_value == "secret-token"
    assert capability.redacted() == {
        "provider": "github",
        "token_env": "GITHUB_TOKEN",
        "token_value": REDACTED_SECRET,
    }


def test_scm_credential_boundary_settings_snapshot_excludes_token_value() -> None:
    snapshot = ScmCredentialBoundary().settings_snapshot(_github_scm())

    assert snapshot == {
        "provider": "github",
        "github_owner": "octo-org",
        "github_repo": "zebra-agent",
        "github_token_env": "GITHUB_TOKEN",
        "github_api_base_url": "https://api.github.com",
        "pull_request_dry_run": True,
    }
    assert "secret-token" not in str(snapshot)


def _local_scm() -> ScmSettings:
    return ScmSettings(
        provider="local-only",
        github_owner=None,
        github_repo=None,
        github_token_env=None,
        github_api_base_url="https://api.github.com",
        pull_request_dry_run=True,
    )


def _github_scm() -> ScmSettings:
    return ScmSettings(
        provider="github",
        github_owner="octo-org",
        github_repo="zebra-agent",
        github_token_env="GITHUB_TOKEN",
        github_api_base_url="https://api.github.com",
        pull_request_dry_run=True,
    )
