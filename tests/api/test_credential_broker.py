from datetime import UTC, datetime

import pytest
from agent_security import CredentialMissingError, EnvironmentCredentialBroker
from zebra_agent_api.credential_broker import build_default_credential_broker
from zebra_agent_config import ScmSettings


def test_default_credential_broker_returns_none_for_local_only() -> None:
    assert build_default_credential_broker(_local_scm()) is None


def test_default_credential_broker_builds_github_environment_broker() -> None:
    broker = build_default_credential_broker(
        _github_scm(),
        env={"GITHUB_TOKEN": "secret-token"},
        now=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    )

    assert isinstance(broker, EnvironmentCredentialBroker)
    capability = broker.request_scm_credential(
        provider="github",
        audience="repo:octo-org/zebra-agent",
        scopes=("pull_request:create",),
        now=datetime(2026, 6, 23, 12, 1, tzinfo=UTC),
    )
    assert capability.token_value == "secret-token"
    assert "secret-token" not in repr(capability)


def test_default_credential_broker_reports_missing_env_value() -> None:
    broker = build_default_credential_broker(
        _github_scm(),
        env={},
        now=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    )

    assert broker is not None
    with pytest.raises(CredentialMissingError, match="environment value"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=datetime(2026, 6, 23, 12, 1, tzinfo=UTC),
        )


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
        pull_request_dry_run=False,
    )
