import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_integrations import (
    GitHubAppCredentialBinding,
    GitHubAppCredentialBroker,
    GitHubAppInstallationToken,
    GitHubAppTokenTransport,
)
from agent_security import (
    CredentialDeniedError,
    CredentialMissingError,
    CredentialTransportError,
    CredentialUnavailableError,
    LocalSecretStore,
)


def test_github_app_credential_broker_issues_capability_from_secret_store(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path)

    capability = broker.request_scm_credential(
        provider="github",
        audience="repo:octo-org/zebra-agent",
        scopes=("pull_request:create",),
        now=_now(),
    )

    assert capability.provider == "github"
    assert capability.audience == "repo:octo-org/zebra-agent"
    assert capability.scopes == ("pull_request:create", "pull_request:read")
    assert capability.token_value == "github-app-token"
    assert "private-key-material" not in repr(capability)


def test_github_app_credential_broker_reports_missing_private_key(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path, create_secret=False)

    with pytest.raises(CredentialMissingError, match="private key is missing"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_github_app_credential_broker_reports_unavailable_secret_store(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path, root_exists=False)

    with pytest.raises(CredentialUnavailableError, match="private key is unavailable"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def test_github_app_credential_broker_rejects_missing_scope(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path)

    with pytest.raises(CredentialDeniedError, match="does not grant requested scopes"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create", "pull_request:merge"),
            now=_now(),
        )


def test_github_app_credential_broker_reports_transport_failure(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path, transport=_FailingGitHubAppTransport())

    with pytest.raises(CredentialTransportError, match="token exchange failed"):
        broker.request_scm_credential(
            provider="github",
            audience="repo:octo-org/zebra-agent",
            scopes=("pull_request:create",),
            now=_now(),
        )


def _broker(
    tmp_path: Path,
    *,
    create_secret: bool = True,
    root_exists: bool = True,
    transport: GitHubAppTokenTransport | None = None,
) -> GitHubAppCredentialBroker:
    root = tmp_path / "secrets"
    if root_exists:
        secret_path = root / "github" / "app"
        secret_path.mkdir(parents=True, exist_ok=True)
        if create_secret:
            (secret_path / "private-key.json").write_text(
                json.dumps({"value": "private-key-material", "version": "v1"}),
                encoding="utf-8",
            )
    if transport is None:
        transport = _FakeGitHubAppTransport()
    return GitHubAppCredentialBroker(
        bindings=(
            GitHubAppCredentialBinding(
                audience="repo:octo-org/zebra-agent",
                installation_id="inst-123",
                app_id="app-123",
                private_key_handle="github/app/private-key",
                scopes=("pull_request:create", "pull_request:read"),
            ),
        ),
        secret_store=LocalSecretStore(root=root),
        transport=transport,
    )


def _now() -> datetime:
    return datetime(2026, 6, 28, 12, 0, tzinfo=UTC)


class _FakeGitHubAppTransport:
    def create_installation_token(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key: str,
        now: datetime,
    ) -> GitHubAppInstallationToken:
        assert app_id == "app-123"
        assert installation_id == "inst-123"
        assert private_key == "private-key-material"
        return GitHubAppInstallationToken(
            token_value="github-app-token",
            expires_at=datetime(2026, 6, 28, 13, 0, tzinfo=UTC),
        )


class _FailingGitHubAppTransport:
    def create_installation_token(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key: str,
        now: datetime,
    ) -> GitHubAppInstallationToken:
        raise RuntimeError("token endpoint offline")
