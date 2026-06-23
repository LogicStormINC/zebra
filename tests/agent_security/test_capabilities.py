from datetime import UTC, datetime, timedelta

import pytest
from agent_security import REDACTED_SECRET, CredentialCapability


def test_credential_capability_redacts_runtime_token() -> None:
    capability = CredentialCapability(
        provider=" github ",
        audience=" repo:octo-org/zebra-agent ",
        scopes=(" pull_request:create ", " pull_request:read "),
        expires_at=datetime(2026, 6, 23, 12, 30, tzinfo=UTC),
        token_value="secret-token",
    )

    assert capability.provider == "github"
    assert capability.audience == "repo:octo-org/zebra-agent"
    assert capability.scopes == ("pull_request:create", "pull_request:read")
    assert capability.redacted() == {
        "provider": "github",
        "audience": "repo:octo-org/zebra-agent",
        "scopes": ["pull_request:create", "pull_request:read"],
        "expires_at": "2026-06-23T12:30:00+00:00",
        "token_value": REDACTED_SECRET,
    }
    assert "secret-token" not in repr(capability)
    assert "secret-token" not in repr(capability.redacted())


def test_credential_capability_detects_expiry() -> None:
    expires_at = datetime(2026, 6, 23, 12, 30, tzinfo=UTC)
    capability = _capability(expires_at=expires_at)

    assert capability.is_expired(expires_at - timedelta(seconds=1)) is False
    assert capability.is_expired(expires_at) is True
    assert capability.is_expired(expires_at + timedelta(seconds=1)) is True


def test_credential_capability_rejects_invalid_identity_fields() -> None:
    with pytest.raises(ValueError, match="provider"):
        _capability(provider=" ")
    with pytest.raises(ValueError, match="audience"):
        _capability(audience=" ")
    with pytest.raises(ValueError, match="scopes"):
        _capability(scopes=())
    with pytest.raises(ValueError, match="scopes"):
        _capability(scopes=("pull_request:create", " "))


def test_credential_capability_requires_timezone_aware_expiry() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _capability(expires_at=datetime(2026, 6, 23, 12, 30))
    with pytest.raises(ValueError, match="timezone-aware"):
        _capability().is_expired(datetime(2026, 6, 23, 12, 30))


def test_credential_capability_rejects_blank_token_value() -> None:
    with pytest.raises(ValueError, match="token_value"):
        _capability(token_value=" ")


def _capability(
    *,
    provider: str = "github",
    audience: str = "repo:octo-org/zebra-agent",
    scopes: tuple[str, ...] = ("pull_request:create",),
    expires_at: datetime = datetime(2026, 6, 23, 12, 30, tzinfo=UTC),
    token_value: str | None = "secret-token",
) -> CredentialCapability:
    return CredentialCapability(
        provider=provider,
        audience=audience,
        scopes=scopes,
        expires_at=expires_at,
        token_value=token_value,
    )
