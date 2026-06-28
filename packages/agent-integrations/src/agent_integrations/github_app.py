from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from agent_security import (
    CredentialCapability,
    CredentialDeniedError,
    CredentialMissingError,
    CredentialTransportError,
    CredentialUnavailableError,
    SecretMissingError,
    SecretStore,
    SecretUnavailableError,
    get_secret_value,
)


@dataclass(frozen=True)
class GitHubAppCredentialBinding:
    audience: str
    installation_id: str
    app_id: str
    private_key_handle: str
    scopes: tuple[str, ...] = ("pull_request:create",)

    def __post_init__(self) -> None:
        audience = self.audience.strip()
        installation_id = self.installation_id.strip()
        app_id = self.app_id.strip()
        private_key_handle = self.private_key_handle.strip()
        scopes = tuple(scope.strip() for scope in self.scopes)
        if not audience:
            raise ValueError("github app audience must not be blank")
        if not installation_id:
            raise ValueError("github app installation_id must not be blank")
        if not app_id:
            raise ValueError("github app app_id must not be blank")
        if not private_key_handle:
            raise ValueError("github app private_key_handle must not be blank")
        if not scopes or any(not scope for scope in scopes):
            raise ValueError("github app scopes must contain non-blank values")
        object.__setattr__(self, "audience", audience)
        object.__setattr__(self, "installation_id", installation_id)
        object.__setattr__(self, "app_id", app_id)
        object.__setattr__(self, "private_key_handle", private_key_handle)
        object.__setattr__(self, "scopes", scopes)


@dataclass(frozen=True)
class GitHubAppInstallationToken:
    token_value: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.token_value.strip():
            raise ValueError("github app token_value must not be blank")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("github app expires_at must be timezone-aware")


class GitHubAppTokenTransport(Protocol):
    def create_installation_token(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key: str,
        now: datetime,
    ) -> GitHubAppInstallationToken:
        raise NotImplementedError


@dataclass(frozen=True)
class GitHubAppCredentialBroker:
    bindings: tuple[GitHubAppCredentialBinding, ...]
    secret_store: SecretStore
    transport: GitHubAppTokenTransport
    backend_name: str = field(default="github_app", init=False)

    def request_scm_credential(
        self,
        *,
        provider: str,
        audience: str,
        scopes: tuple[str, ...],
        now: datetime,
    ) -> CredentialCapability:
        request = _GitHubAppCredentialRequest(
            provider=provider,
            audience=audience,
            scopes=scopes,
        )
        binding = self._find_binding(request)
        if binding is None:
            raise CredentialMissingError("github app credential binding is missing")
        if not set(request.scopes).issubset(set(binding.scopes)):
            raise CredentialDeniedError("github app binding does not grant requested scopes")
        try:
            private_key = get_secret_value(
                self.secret_store,
                handle=binding.private_key_handle,
            )
        except SecretMissingError as error:
            raise CredentialMissingError("github app private key is missing") from error
        except SecretUnavailableError as error:
            raise CredentialUnavailableError("github app private key is unavailable") from error
        try:
            token = self.transport.create_installation_token(
                app_id=binding.app_id,
                installation_id=binding.installation_id,
                private_key=private_key,
                now=now,
            )
        except CredentialTransportError:
            raise
        except Exception as error:
            raise CredentialTransportError("github app token exchange failed") from error
        return CredentialCapability(
            provider="github",
            audience=binding.audience,
            scopes=binding.scopes,
            expires_at=token.expires_at,
            token_value=token.token_value,
        )

    def _find_binding(
        self,
        request: _GitHubAppCredentialRequest,
    ) -> GitHubAppCredentialBinding | None:
        if request.provider != "github":
            raise CredentialDeniedError("unsupported credential provider")
        for binding in self.bindings:
            if binding.audience == request.audience:
                return binding
        return None


@dataclass(frozen=True)
class _GitHubAppCredentialRequest:
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
