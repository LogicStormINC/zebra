from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_security import CredentialBroker, CredentialBrokerError
from zebra_agent_config import ScmSettings

from agent_integrations.scm_errors import ScmUnavailableError


@dataclass(frozen=True)
class CredentialLookupResult:
    token_value: str | None
    credential_source: str
    credential_backend: str | None = None


def token_from_broker(
    settings: ScmSettings,
    *,
    credential_broker: CredentialBroker,
    now: datetime,
) -> CredentialLookupResult:
    return github_token_from_broker(
        owner=settings.github_owner,
        repo=settings.github_repo,
        credential_broker=credential_broker,
        now=now,
    )


def github_token_from_broker(
    *,
    owner: str | None,
    repo: str | None,
    credential_broker: CredentialBroker,
    now: datetime,
) -> CredentialLookupResult:
    try:
        capability = credential_broker.request_scm_credential(
            provider="github",
            audience=github_repository_audience(owner, repo),
            scopes=("pull_request:create",),
            now=now,
        )
    except CredentialBrokerError as error:
        raise ScmUnavailableError(
            str(error),
            metadata={
                "credential_source": "broker",
                "credential_backend": "environment",
            },
        ) from error
    return CredentialLookupResult(
        token_value=capability.token_value,
        credential_source="broker",
        credential_backend="environment",
    )


def github_repository_audience(owner: str | None, repo: str | None) -> str:
    if owner is None or repo is None:
        raise ScmUnavailableError("github owner and repo are required")
    return f"repo:{owner.strip()}/{repo.strip()}"
