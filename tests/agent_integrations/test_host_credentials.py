from datetime import UTC, datetime

import pytest
from agent_integrations import ConfiguredHmacHostCredentialResolver


def test_configured_hmac_credential_is_real_bounded_and_secret_in_repr() -> None:
    resolver = ConfiguredHmacHostCredentialResolver(
        "real-workload-secret",
        now=lambda: datetime(2026, 9, 19, tzinfo=UTC),
    )

    credential = resolver.issue(
        credential_ref="credentials/trench-hmac",
        workload_identity_ref="workload/zebra",
        audience="https://trench.example.com",
        scopes=("event.read",),
        ttl_seconds=900,
    )

    assert credential.token == "real-workload-secret"
    assert credential.scopes == ("event.read",)
    assert credential.expires_at_epoch == 1789776900
    assert "real-workload-secret" not in repr(resolver)


@pytest.mark.parametrize("token", ["", "   ", "compat:credentials/trench"])
def test_configured_hmac_credential_rejects_missing_or_placeholder_token(token: str) -> None:
    with pytest.raises(ValueError, match="credential is invalid"):
        ConfiguredHmacHostCredentialResolver(token)


def test_configured_hmac_credential_rejects_non_https_audience() -> None:
    resolver = ConfiguredHmacHostCredentialResolver("real-workload-secret")
    with pytest.raises(ValueError, match="HTTPS origin"):
        resolver.issue(
            credential_ref="credentials/trench-hmac",
            workload_identity_ref="workload/zebra",
            audience="http://trench.internal",
            scopes=("event.read",),
            ttl_seconds=900,
        )
