"""Bounded PyJWT/JWKS decoding for the Host Grant trust boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Protocol, cast

import jwt
from agent_core.domain.host_authority import HostSessionGrant
from jwt import PyJWKClient

from agent_security.host_grant import (
    HostGrantSecurityError,
    HostGrantVerificationConfig,
    JwtAlgorithm,
)


class HostGrantDecodeError(HostGrantSecurityError):
    """Raised when a bearer token cannot be decoded and validated."""


class JwksKeyResolver(Protocol):
    """Resolve a signing key only for a registry-approved JWKS URI."""

    def resolve(self, jwks_uri: str, token: str) -> Any:
        """Return a key suitable for PyJWT signature verification."""


@dataclass(frozen=True)
class DecodedJwtGrant:
    """Decoded claims and pinned algorithm, without retaining the raw token."""

    grant: HostSessionGrant
    algorithm: JwtAlgorithm


@dataclass
class CachingJwksKeyResolver:
    """Bounded timeout/cache wrapper around PyJWT's JWKS client."""

    timeout_seconds: float = 5.0
    cache_lifespan_seconds: int = 300
    _clients: dict[str, PyJWKClient] = field(default_factory=dict, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("JWKS timeout must be between 0 and 30 seconds")
        if not 0 < self.cache_lifespan_seconds <= 3_600:
            raise ValueError("JWKS cache lifespan must be between 0 and 3600 seconds")

    def resolve(self, jwks_uri: str, token: str) -> Any:
        with self._lock:
            client = self._clients.get(jwks_uri)
            if client is None:
                client = PyJWKClient(
                    jwks_uri,
                    cache_jwk_set=True,
                    lifespan=self.cache_lifespan_seconds,
                    timeout=self.timeout_seconds,
                )
                self._clients[jwks_uri] = client
        try:
            return client.get_signing_key_from_jwt(token).key
        except Exception as exc:  # PyJWT and transport errors must not leak details.
            raise HostGrantDecodeError("Host Grant signing key resolution failed") from exc


@dataclass(frozen=True)
class PyJwtHostGrantDecoder:
    """Decode one registry-bound token with explicit algorithm and claim pins."""

    key_resolver: JwksKeyResolver

    def decode(
        self,
        token: str,
        *,
        config: HostGrantVerificationConfig,
    ) -> DecodedJwtGrant:
        if not isinstance(token, str) or not token.strip() or len(token) > 32_768:
            raise HostGrantDecodeError("Host Grant token is missing or exceeds its bound")
        try:
            header = jwt.get_unverified_header(token)
            raw_algorithm = header.get("alg")
            if not isinstance(raw_algorithm, str):
                raise HostGrantDecodeError("Host Grant algorithm header is missing")
            algorithm = JwtAlgorithm(raw_algorithm)
        except (KeyError, TypeError, ValueError, jwt.PyJWTError) as exc:
            raise HostGrantDecodeError("Host Grant header is invalid") from exc
        if algorithm not in config.algorithms:
            raise HostGrantDecodeError("Host Grant algorithm is not registered")
        try:
            key = self.key_resolver.resolve(config.jwks_uri, token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm.value],
                audience=config.audience,
                issuer=config.issuer,
                leeway=config.clock_skew_seconds,
                options=cast(
                    Any,
                    {"require": ("iss", "aud", "sub", "jti", "iat", "nbf", "exp")},
                ),
            )
            grant = HostSessionGrant.model_validate(claims)
        except Exception as exc:  # Signature, claim and model failures are one safe error.
            if isinstance(exc, HostGrantDecodeError):
                raise
            raise HostGrantDecodeError("Host Grant signature or claims are invalid") from exc
        return DecodedJwtGrant(grant=grant, algorithm=algorithm)
