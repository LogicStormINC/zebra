from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from agent_security.capabilities import CredentialCapability


class CredentialBrokerError(ValueError):
    """Base error for credential broker requests."""


class CredentialMissingError(CredentialBrokerError):
    """Raised when no matching credential exists."""


class CredentialDeniedError(CredentialBrokerError):
    """Raised when a matching credential is not permitted for the request."""


class CredentialUnavailableError(CredentialBrokerError):
    """Raised when the credential broker cannot serve requests."""


class CredentialTransportError(CredentialBrokerError):
    """Raised when a provider-backed credential exchange transport fails."""


class CredentialBroker(Protocol):
    def request_scm_credential(
        self,
        *,
        provider: str,
        audience: str,
        scopes: tuple[str, ...],
        now: datetime,
    ) -> CredentialCapability:
        raise NotImplementedError


@dataclass(frozen=True)
class InMemoryCredentialBroker:
    capabilities: tuple[CredentialCapability, ...] = ()
    denied_audiences: frozenset[str] = field(default_factory=frozenset)
    unavailable: bool = False
    backend_name: str = field(default="environment", init=False)

    @classmethod
    def with_capabilities(
        cls,
        capabilities: Iterable[CredentialCapability],
    ) -> InMemoryCredentialBroker:
        return cls(capabilities=tuple(capabilities))

    def request_scm_credential(
        self,
        *,
        provider: str,
        audience: str,
        scopes: tuple[str, ...],
        now: datetime,
    ) -> CredentialCapability:
        if self.unavailable:
            raise CredentialUnavailableError("credential broker is unavailable")
        request = _CredentialRequest(provider=provider, audience=audience, scopes=scopes)
        if request.audience in self.denied_audiences:
            raise CredentialDeniedError("credential request denied for audience")
        capability = self._find_capability(request)
        if capability is None:
            raise CredentialMissingError("credential is missing")
        if capability.is_expired(now):
            raise CredentialMissingError("credential is expired")
        if not set(request.scopes).issubset(set(capability.scopes)):
            raise CredentialDeniedError("credential does not grant requested scopes")
        return capability

    def _find_capability(self, request: _CredentialRequest) -> CredentialCapability | None:
        for capability in self.capabilities:
            if capability.provider == request.provider and capability.audience == request.audience:
                return capability
        return None


@dataclass(frozen=True)
class _CredentialRequest:
    provider: str
    audience: str
    scopes: tuple[str, ...]

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
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "audience", audience)
        object.__setattr__(self, "scopes", scopes)
