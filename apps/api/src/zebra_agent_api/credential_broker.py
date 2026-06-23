from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from agent_security import (
    CredentialBroker,
    EnvironmentCredentialBinding,
    EnvironmentCredentialBroker,
)
from zebra_agent_config import ScmSettings

DEFAULT_CREDENTIAL_TTL_SECONDS = 3600


def build_default_credential_broker(
    settings: ScmSettings,
    *,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> CredentialBroker | None:
    if settings.provider == "local-only":
        return None
    if settings.provider != "github":
        return None
    if settings.github_owner is None or settings.github_repo is None:
        raise ValueError("github owner and repo are required")
    if settings.github_token_env is None:
        raise ValueError("github token environment name is required")
    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return EnvironmentCredentialBroker(
        bindings=(
            EnvironmentCredentialBinding(
                provider="github",
                audience=f"repo:{settings.github_owner.strip()}/{settings.github_repo.strip()}",
                scopes=("pull_request:create",),
                token_env=settings.github_token_env,
                expires_at=issued_at + timedelta(seconds=DEFAULT_CREDENTIAL_TTL_SECONDS),
            ),
        ),
        env=env or os.environ,
    )
