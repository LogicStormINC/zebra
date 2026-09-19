"""Configured short-lived HMAC credentials for Host workload egress."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent_core.ports.host_credential_resolver import (
    EphemeralHostCredential,
    validate_credential_ref,
)


@dataclass(frozen=True, slots=True)
class ConfiguredHmacHostCredentialResolver:
    """Expose a configured workload secret through the credential Port.

    This is the bounded HMAC compatibility adapter for deployments that have
    not yet installed OAuth workload identity or mTLS. The secret remains in
    process memory and is excluded from repr/log output.
    """

    token: str = field(repr=False)
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC), repr=False)

    def __post_init__(self) -> None:
        token = self.token.strip()
        if not token or token.startswith("compat:"):
            raise ValueError("configured Host workload credential is invalid")
        object.__setattr__(self, "token", token)

    def issue(
        self,
        *,
        credential_ref: str,
        workload_identity_ref: str,
        audience: str,
        scopes: tuple[str, ...],
        ttl_seconds: int,
    ) -> EphemeralHostCredential:
        validate_credential_ref(credential_ref)
        if not workload_identity_ref.strip():
            raise ValueError("workload identity reference must be non-blank")
        if not audience.startswith("https://"):
            raise ValueError("Host credential audience must be an HTTPS origin")
        if ttl_seconds <= 0 or ttl_seconds > 3600:
            raise ValueError("Host credential ttl is outside its bounds")
        issued_at = self.now()
        if issued_at.tzinfo is None or issued_at.utcoffset() is None:
            raise ValueError("Host credential clock must be timezone-aware")
        return EphemeralHostCredential(
            token=self.token,
            audience=audience,
            scopes=tuple(scopes),
            expires_at_epoch=int(issued_at.timestamp()) + ttl_seconds,
        )
