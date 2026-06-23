from __future__ import annotations

from datetime import datetime

from agent_security import CredentialBroker, CredentialBrokerError
from zebra_agent_config import ScmSettings

from agent_integrations.scm_errors import ScmUnavailableError


def token_from_broker(
    settings: ScmSettings,
    *,
    credential_broker: CredentialBroker,
    now: datetime,
) -> str | None:
    try:
        capability = credential_broker.request_scm_credential(
            provider="github",
            audience=github_repository_audience(settings.github_owner, settings.github_repo),
            scopes=("pull_request:create",),
            now=now,
        )
    except CredentialBrokerError as error:
        raise ScmUnavailableError(str(error)) from error
    return capability.token_value


def github_repository_audience(owner: str | None, repo: str | None) -> str:
    if owner is None or repo is None:
        raise ScmUnavailableError("github owner and repo are required")
    return f"repo:{owner.strip()}/{repo.strip()}"
