from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from agent_security.broker import CredentialDeniedError, CredentialMissingError
from agent_security.capabilities import CredentialCapability


@dataclass(frozen=True)
class EnvironmentCredentialBinding:
    provider: str
    audience: str
    scopes: tuple[str, ...]
    token_env: str
    expires_at: datetime

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        audience = self.audience.strip()
        scopes = tuple(scope.strip() for scope in self.scopes)
        token_env = self.token_env.strip()
        if not provider:
            raise ValueError("credential provider must not be blank")
        if not audience:
            raise ValueError("credential audience must not be blank")
        if not scopes or any(not scope for scope in scopes):
            raise ValueError("credential scopes must contain non-blank values")
        if not token_env:
            raise ValueError("credential token_env must not be blank")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("credential expires_at must be timezone-aware")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "audience", audience)
        object.__setattr__(self, "scopes", scopes)
        object.__setattr__(self, "token_env", token_env)


@dataclass(frozen=True)
class EnvironmentCredentialBroker:
    bindings: tuple[EnvironmentCredentialBinding, ...]
    env: Mapping[str, str] = field(default_factory=lambda: os.environ, repr=False)

    def request_scm_credential(
        self,
        *,
        provider: str,
        audience: str,
        scopes: tuple[str, ...],
        now: datetime,
    ) -> CredentialCapability:
        request = _EnvironmentCredentialRequest(
            provider=provider,
            audience=audience,
            scopes=scopes,
        )
        binding = self._find_binding(request)
        if binding is None:
            raise CredentialMissingError("credential binding is missing")
        if not set(request.scopes).issubset(set(binding.scopes)):
            raise CredentialDeniedError("credential binding does not grant requested scopes")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if now >= binding.expires_at:
            raise CredentialMissingError("credential binding is expired")
        token_value = self.env.get(binding.token_env)
        if token_value is None or not token_value.strip():
            raise CredentialMissingError("credential environment value is missing")
        return CredentialCapability(
            provider=binding.provider,
            audience=binding.audience,
            scopes=binding.scopes,
            expires_at=binding.expires_at,
            token_value=token_value,
        )

    def _find_binding(
        self,
        request: _EnvironmentCredentialRequest,
    ) -> EnvironmentCredentialBinding | None:
        provider_seen = False
        for binding in self.bindings:
            if binding.provider != request.provider:
                continue
            provider_seen = True
            if binding.audience == request.audience:
                return binding
        if not provider_seen:
            raise CredentialDeniedError("unsupported credential provider")
        return None


@dataclass(frozen=True)
class _EnvironmentCredentialRequest:
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
