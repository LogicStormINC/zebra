from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent_security.credentials import REDACTED_SECRET


class SecretStoreError(ValueError):
    """Base error for secret-store requests."""


class SecretMissingError(SecretStoreError):
    """Raised when a requested secret does not exist."""


class SecretUnavailableError(SecretStoreError):
    """Raised when the secret store cannot serve requests."""


@dataclass(frozen=True)
class SecretMaterial:
    handle: str
    backend: str
    version: str | None = None
    value: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        handle = self.handle.strip()
        backend = self.backend.strip()
        version = self.version.strip() if self.version is not None else None
        if not handle:
            raise ValueError("secret handle must not be blank")
        if not backend:
            raise ValueError("secret backend must not be blank")
        if version is not None and not version:
            raise ValueError("secret version must not be blank when provided")
        if self.value is not None and not self.value.strip():
            raise ValueError("secret value must not be blank when provided")
        object.__setattr__(self, "handle", handle)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "version", version)

    def redacted(self) -> dict[str, object]:
        return {
            "handle": self.handle,
            "backend": self.backend,
            "version": self.version,
            "value": REDACTED_SECRET if self.value else None,
        }


class SecretStore(Protocol):
    def get_secret(self, *, handle: str) -> SecretMaterial:
        raise NotImplementedError


@dataclass(frozen=True)
class InMemorySecretStore:
    secrets: dict[str, SecretMaterial] = field(default_factory=dict)
    unavailable: bool = False

    def get_secret(self, *, handle: str) -> SecretMaterial:
        normalized_handle = handle.strip()
        if not normalized_handle:
            raise ValueError("secret handle must not be blank")
        if self.unavailable:
            raise SecretUnavailableError("secret store is unavailable")
        secret = self.secrets.get(normalized_handle)
        if secret is None:
            raise SecretMissingError("secret is missing")
        return secret
