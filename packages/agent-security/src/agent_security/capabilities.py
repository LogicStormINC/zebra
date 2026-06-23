from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agent_security.credentials import REDACTED_SECRET


@dataclass(frozen=True)
class CredentialCapability:
    provider: str
    audience: str
    scopes: tuple[str, ...]
    expires_at: datetime
    token_value: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        audience = self.audience.strip()
        scopes = tuple(scope.strip() for scope in self.scopes)
        if not provider:
            raise ValueError("credential provider must not be blank")
        if not audience:
            raise ValueError("credential audience must not be blank")
        if not scopes or any(not scope for scope in scopes):
            raise ValueError("credential scopes must contain non-blank values")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("credential expires_at must be timezone-aware")
        if self.token_value is not None and not self.token_value.strip():
            raise ValueError("credential token_value must not be blank when provided")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "audience", audience)
        object.__setattr__(self, "scopes", scopes)

    def is_expired(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return now >= self.expires_at

    def redacted(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "audience": self.audience,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at.isoformat(),
            "token_value": REDACTED_SECRET if self.token_value else None,
        }
