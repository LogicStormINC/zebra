"""Provider-neutral Host Grant verification contract.

JWT parsing, signature verification and JWKS retrieval belong to an adapter. This
module accepts only already-decoded core claims and never stores the bearer token.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostGrantMismatchError,
    HostGrantScopeError,
    HostResourceRef,
    HostSessionGrant,
)


class HostGrantSecurityError(ValueError):
    """Base error for fail-closed Host Grant verification."""


class HostGrantAlgorithmError(HostGrantSecurityError):
    """Raised when the decoded JWT algorithm is not explicitly allowed."""


class HostGrantBindingError(HostGrantSecurityError):
    """Raised when a grant does not match trusted verifier bindings."""


class JwtAlgorithm(StrEnum):
    RS256 = "RS256"
    ES256 = "ES256"


@dataclass(frozen=True)
class HostGrantVerificationConfig:
    issuer: str
    audience: str
    jwks_uri: str
    allowed_origins: tuple[str, ...]
    algorithms: frozenset[JwtAlgorithm] = frozenset({JwtAlgorithm.RS256})
    clock_skew_seconds: int = 30
    require_jti: bool = True

    def __post_init__(self) -> None:
        issuer = _https_origin(self.issuer, "issuer")
        jwks_uri = _https_url(self.jwks_uri, "jwks_uri")
        audience = _required_text(self.audience, "audience", 512)
        origins = tuple(_https_origin(origin, "allowed_origin") for origin in self.allowed_origins)
        if not origins or len(set(origins)) != len(origins):
            raise ValueError("allowed_origins must contain unique exact origins")
        if any(origin == "*" for origin in origins):
            raise ValueError("allowed_origins must not contain wildcard origin")
        if not self.algorithms or not self.algorithms <= frozenset(JwtAlgorithm):
            raise ValueError("algorithms must use an explicit supported asymmetric algorithm")
        if isinstance(self.clock_skew_seconds, bool) or not 0 <= self.clock_skew_seconds <= 300:
            raise ValueError("clock_skew_seconds must be between 0 and 300")
        object.__setattr__(self, "issuer", issuer)
        object.__setattr__(self, "audience", audience)
        object.__setattr__(self, "jwks_uri", jwks_uri)
        object.__setattr__(self, "allowed_origins", origins)


@dataclass(frozen=True)
class VerifiedHostGrant:
    """Secret-free verified result passed to downstream composition."""

    context: HostContextEnvelope
    grant_id: str
    algorithm: JwtAlgorithm


class DecodedHostGrant(Protocol):
    """Adapter output after JWT signature/claim decoding, without raw token."""

    grant: HostSessionGrant
    algorithm: JwtAlgorithm


@dataclass(frozen=True)
class HostGrantVerifier:
    config: HostGrantVerificationConfig

    def verify(
        self,
        grant: HostSessionGrant,
        *,
        algorithm: JwtAlgorithm,
        now: datetime,
        expected_host_app_id: str | None = None,
        required_scopes: Iterable[str] = (),
        required_resources: Iterable[HostResourceRef] = (),
    ) -> VerifiedHostGrant:
        if algorithm not in self.config.algorithms:
            raise HostGrantAlgorithmError(f"JWT algorithm is not allowed: {algorithm.value}")
        if self.config.require_jti and not grant.jti.strip():
            raise HostGrantBindingError("Host Grant requires a non-blank jti")
        try:
            context = grant.validate_against(
                now=now,
                expected_issuer=self.config.issuer,
                expected_audience=self.config.audience,
                allowed_origins=self.config.allowed_origins,
                expected_host_app_id=expected_host_app_id,
                clock_skew_seconds=self.config.clock_skew_seconds,
            )
        except (HostGrantMismatchError, HostGrantScopeError, ValueError) as exc:
            raise HostGrantBindingError("Host Grant trusted binding validation failed") from exc
        try:
            for scope in required_scopes:
                context.require_scope(scope)
            for resource in required_resources:
                context.require_resource(resource)
        except HostGrantScopeError as exc:
            raise HostGrantBindingError(
                "Host Grant requested scope or resource is not granted"
            ) from exc
        return VerifiedHostGrant(context=context, grant_id=grant.jti, algorithm=algorithm)


def _required_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} must be non-blank and at most {maximum} characters")
    return normalized


def _https_origin(value: str, field_name: str) -> str:
    normalized = _required_text(value, field_name, 2_048)
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
        raise ValueError(f"{field_name} must be an HTTPS origin without a path")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must not contain query or fragment")
    host = parsed.hostname
    if host is None:
        raise ValueError(f"{field_name} must contain a host")
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"https://{host.lower()}{port}"


def _https_url(value: str, field_name: str) -> str:
    normalized = _required_text(value, field_name, 2_048)
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{field_name} must be an HTTPS URL without credentials")
    return normalized
