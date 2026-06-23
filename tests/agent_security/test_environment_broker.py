from datetime import UTC, datetime, timedelta

import pytest
from agent_security import (
    REDACTED_SECRET,
    CredentialDeniedError,
    CredentialMissingError,
    EnvironmentCredentialBinding,
    EnvironmentCredentialBroker,
)


def test_environment_broker_issues_capability_from_env_value() -> None:
    broker = EnvironmentCredentialBroker(
        bindings=(_github_binding(),),
        env={"GITHUB_TOKEN": "secret-token"},
    )

    capability = broker.request_scm_credential(
        provider="github",
        audience="repo:octo-org/zebra-agent",
        scopes=("pull_request:create",),
        now=_now(),
    )

    assert capability.provider == "github"
    assert capability.audience == "repo:octo-org/zebra-agent"
    assert capability.scopes == ("pull_request:create", "pull_request:read")
    assert capability.token_value == "secret-token"
    assert capability.redacted()["token_value"] == REDACTED_SECRET
    assert "secret-token" not in repr(capability)
    assert "secret-token" not in repr(capability.redacted())
    assert "secret-token" not in repr(broker)


def test_environment_broker_rejects_missing_env_value() -> None:
    broker = EnvironmentCredentialBroker(bindings=(_github_binding(),), env={})

    with pytest.raises(CredentialMissingError, match="environment value"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_environment_broker_rejects_unsupported_provider() -> None:
    broker = EnvironmentCredentialBroker(
        bindings=(_github_binding(),),
        env={"GITHUB_TOKEN": "secret-token"},
    )

    with pytest.raises(CredentialDeniedError, match="provider"):
        broker.request_scm_credential(
            provider="gitlab",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_environment_broker_rejects_unsupported_scope() -> None:
    broker = EnvironmentCredentialBroker(
        bindings=(_github_binding(),),
        env={"GITHUB_TOKEN": "secret-token"},
    )

    with pytest.raises(CredentialDeniedError, match="scopes"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create", "pull_request:merge"),
            now=_now(),
        )


def test_environment_broker_rejects_expired_binding() -> None:
    broker = EnvironmentCredentialBroker(
        bindings=(_github_binding(expires_at=_now() - timedelta(seconds=1)),),
        env={"GITHUB_TOKEN": "secret-token"},
    )

    with pytest.raises(CredentialMissingError, match="expired"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_environment_broker_validates_binding_and_request_fields() -> None:
    with pytest.raises(ValueError, match="token_env"):
        _github_binding(token_env=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        _github_binding(expires_at=datetime(2026, 6, 23, 12, 30))
    broker = EnvironmentCredentialBroker(bindings=(_github_binding(),), env={})
    with pytest.raises(ValueError, match="timezone-aware"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=datetime(2026, 6, 23, 12, 0),
        )


def _github_binding(
    *,
    token_env: str = "GITHUB_TOKEN",
    expires_at: datetime = datetime(2026, 6, 23, 12, 30, tzinfo=UTC),
) -> EnvironmentCredentialBinding:
    return EnvironmentCredentialBinding(
        provider="github",
        audience="repo:octo-org/zebra-agent",
        scopes=("pull_request:create", "pull_request:read"),
        token_env=token_env,
        expires_at=expires_at,
    )


def _now() -> datetime:
    return datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
