from datetime import UTC, datetime, timedelta

import pytest
from agent_security import (
    REDACTED_SECRET,
    CredentialCapability,
    CredentialDeniedError,
    CredentialMissingError,
    CredentialUnavailableError,
    InMemoryCredentialBroker,
)


def test_in_memory_broker_issues_scm_credential_by_provider_and_audience() -> None:
    capability = _capability()
    broker = InMemoryCredentialBroker.with_capabilities([capability])

    issued = broker.request_scm_credential(
        provider=" github ",
        audience=" repo:octo-org/zebra-agent ",
        scopes=(" pull_request:create ",),
        now=_now(),
    )

    assert issued == capability
    assert issued.redacted()["token_value"] == REDACTED_SECRET
    assert "secret-token" not in repr(issued)
    assert "secret-token" not in repr(issued.redacted())


def test_in_memory_broker_rejects_missing_credential() -> None:
    broker = InMemoryCredentialBroker()

    with pytest.raises(CredentialMissingError, match="missing"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_in_memory_broker_rejects_denied_audience() -> None:
    broker = InMemoryCredentialBroker(
        capabilities=(_capability(),),
        denied_audiences=frozenset({"repo:octo-org/zebra-agent"}),
    )

    with pytest.raises(CredentialDeniedError, match="denied"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_in_memory_broker_rejects_missing_scope() -> None:
    broker = InMemoryCredentialBroker.with_capabilities([_capability()])

    with pytest.raises(CredentialDeniedError, match="scopes"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create", "pull_request:merge"),
            now=_now(),
        )


def test_in_memory_broker_reports_unavailable() -> None:
    broker = InMemoryCredentialBroker(unavailable=True)

    with pytest.raises(CredentialUnavailableError, match="unavailable"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_in_memory_broker_rejects_expired_credential() -> None:
    broker = InMemoryCredentialBroker.with_capabilities(
        [_capability(expires_at=_now() - timedelta(seconds=1))]
    )

    with pytest.raises(CredentialMissingError, match="expired"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_in_memory_broker_validates_request() -> None:
    broker = InMemoryCredentialBroker.with_capabilities([_capability()])

    with pytest.raises(ValueError, match="provider"):
        broker.request_scm_credential(
            provider=" ",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )
    with pytest.raises(ValueError, match="audience"):
        broker.request_scm_credential(
            provider="github",
            audience=" ",
            scopes=("pull_request:create",),
            now=_now(),
        )
    with pytest.raises(ValueError, match="scopes"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=(),
            now=_now(),
        )


def _capability(
    *,
    expires_at: datetime = datetime(2026, 6, 23, 12, 30, tzinfo=UTC),
) -> CredentialCapability:
    return CredentialCapability(
        provider="github",
        audience="repo:octo-org/zebra-agent",
        scopes=("pull_request:create", "pull_request:read"),
        expires_at=expires_at,
        token_value="secret-token",
    )


def _now() -> datetime:
    return datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
