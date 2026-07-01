from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
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
class LocalSecretStore:
    root: Path
    backend_name: str = "local-file"

    def __post_init__(self) -> None:
        if not self.backend_name.strip():
            raise ValueError("secret backend_name must not be blank")

    def get_secret(self, *, handle: str) -> SecretMaterial:
        normalized_handle = _normalize_handle(handle)
        root = self.root.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise SecretUnavailableError("secret store root is unavailable")
        path = _secret_document_path(root=root, handle=normalized_handle)
        if not path.exists():
            raise SecretMissingError("secret is missing")
        if not path.is_file():
            raise SecretUnavailableError("secret document is unavailable")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SecretUnavailableError("secret document is unreadable") from error
        if not isinstance(payload, dict):
            raise SecretUnavailableError("secret document must be an object")
        value = payload.get("value")
        version = payload.get("version")
        if not isinstance(value, str) or not value.strip():
            raise SecretUnavailableError("secret document value is unavailable")
        if version is not None and not isinstance(version, str):
            raise SecretUnavailableError("secret document version is invalid")
        return SecretMaterial(
            handle=normalized_handle,
            backend=self.backend_name,
            version=version,
            value=value,
        )


@dataclass(frozen=True)
class InMemorySecretStore:
    secrets: dict[str, SecretMaterial] = field(default_factory=dict)
    unavailable: bool = False

    def get_secret(self, *, handle: str) -> SecretMaterial:
        normalized_handle = _normalize_handle(handle)
        if self.unavailable:
            raise SecretUnavailableError("secret store is unavailable")
        secret = self.secrets.get(normalized_handle)
        if secret is None:
            raise SecretMissingError("secret is missing")
        return secret


def get_secret_value(secret_store: SecretStore, *, handle: str) -> str:
    secret = secret_store.get_secret(handle=handle)
    if secret.value is None:
        raise SecretUnavailableError("secret value is unavailable")
    return secret.value


def _normalize_handle(handle: str) -> str:
    normalized_handle = handle.strip()
    if not normalized_handle:
        raise ValueError("secret handle must not be blank")
    parts = normalized_handle.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError("secret handle must not contain empty or traversal segments")
    return "/".join(parts)


def _secret_document_path(*, root: Path, handle: str) -> Path:
    path = root.joinpath(*handle.split("/")).with_suffix(".json")
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("secret handle resolves outside the secret store root") from error
    return resolved
