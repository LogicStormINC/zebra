"""Bounded PyJWT/JWKS decoding for the Host Grant trust boundary."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Any, Protocol, cast

import jwt
from agent_core.domain.host_authority import HostSessionGrant
from jwt import PyJWKSet

from agent_security.host_grant import (
    HostGrantSecurityError,
    HostGrantVerificationConfig,
    JwtAlgorithm,
)


class HostGrantDecodeError(HostGrantSecurityError):
    """Raised when a bearer token cannot be decoded and validated."""


class JwksKeyResolver(Protocol):
    """Resolve a signing key only for a registry-approved JWKS URI."""

    def resolve(self, jwks_uri: str, token: str, *, deadline: float | None = None) -> Any:
        """Return a key suitable for PyJWT signature verification."""


@dataclass(frozen=True)
class DecodedJwtGrant:
    """Decoded claims and pinned algorithm, without retaining the raw token."""

    grant: HostSessionGrant
    algorithm: JwtAlgorithm


_MAX_JWKS_BYTES = 65_536
_MAX_JWKS_KEYS = 64
_MAX_JWKS_CACHE = 32
_FETCH_SCRIPT = """import json,sys,urllib.request
uri,timeout,maximum=json.load(sys.stdin)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None
request=urllib.request.Request(uri,headers={"Accept-Encoding":"identity"})
with urllib.request.build_opener(NoRedirect()).open(request,timeout=timeout) as response:
    if response.headers.get("Content-Encoding","identity").strip().lower()!="identity":
        raise ValueError("unexpected JWKS encoding")
    length=response.headers.get("Content-Length")
    if length is not None and not 0<=int(length)<=maximum:
        raise ValueError("oversized JWKS")
    content=response.read(maximum+1)
    if len(content)>maximum:
        raise ValueError("oversized JWKS")
sys.stdout.buffer.write(content)
"""


def _remaining(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Host Grant JWKS deadline exceeded")
    return remaining


@dataclass
class CachingJwksKeyResolver:
    """Bounded cache and killable native DNS/HTTP, with no bearer in the child."""

    timeout_seconds: float = 5.0
    cache_lifespan_seconds: int = 300
    _sets: OrderedDict[str, tuple[float, PyJWKSet]] = field(
        default_factory=OrderedDict, init=False, repr=False
    )
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 30:
            raise ValueError("JWKS timeout must be between 0 and 30 seconds")
        if not 0 < self.cache_lifespan_seconds <= 3_600:
            raise ValueError("JWKS cache lifespan must be between 0 and 3600 seconds")

    def resolve(self, jwks_uri: str, token: str, *, deadline: float | None = None) -> Any:
        deadline = (
            min(deadline, monotonic() + self.timeout_seconds)
            if deadline is not None
            else (monotonic() + self.timeout_seconds)
        )
        if not math.isfinite(deadline):
            raise ValueError("JWKS deadline must be finite")
        # ponytail: cache hits/misses share one lock, so parallel misses serialize.
        # Admission is deadline-bounded; per-URI locks are the throughput upgrade.
        if not self._lock.acquire(timeout=_remaining(deadline)):
            raise TimeoutError("Host Grant JWKS cache admission deadline exceeded")
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 512:
                raise ValueError("JWKS signing key id is missing or exceeds its bound")
            cached = self._sets.get(jwks_uri)
            fresh = cached is None or monotonic() - cached[0] >= self.cache_lifespan_seconds
            keys = self._fetch(jwks_uri, deadline) if fresh or cached is None else cached[1]
            found = next(
                (
                    key
                    for key in keys.keys
                    if key.key_id == kid and key.public_key_use in ("sig", None)
                ),
                None,
            )
            if found is None and not fresh:
                # One rotation refresh, not a second fetch on a cold unknown kid.
                keys = self._fetch(jwks_uri, deadline)
                found = next(
                    (
                        key
                        for key in keys.keys
                        if key.key_id == kid and key.public_key_use in ("sig", None)
                    ),
                    None,
                )
            _remaining(deadline)
            self._sets[jwks_uri] = (
                (monotonic(), keys)
                if fresh
                else (cached if cached is not None and keys is cached[1] else (monotonic(), keys))
            )
            self._sets.move_to_end(jwks_uri)
            while len(self._sets) > _MAX_JWKS_CACHE:
                self._sets.popitem(last=False)
            if found is None or found.public_key_use not in ("sig", None):
                raise ValueError("JWKS signing key id is not registered")
            return found.key
        except TimeoutError:
            raise
        except Exception as exc:
            raise HostGrantDecodeError("Host Grant signing key resolution failed") from exc
        finally:
            self._lock.release()

    def prefetch(self, jwks_uri: str, *, deadline: float) -> None:
        """Warm registry-pinned public keys without a token or authorization decision."""
        deadline = min(deadline, monotonic() + self.timeout_seconds)
        if not math.isfinite(deadline):
            raise ValueError("JWKS deadline must be finite")
        if not self._lock.acquire(timeout=_remaining(deadline)):
            raise TimeoutError("Host Grant JWKS cache admission deadline exceeded")
        try:
            cached = self._sets.get(jwks_uri)
            if cached is None or monotonic() - cached[0] >= self.cache_lifespan_seconds:
                keys = self._fetch(jwks_uri, deadline)
                _remaining(deadline)
                self._sets[jwks_uri] = (monotonic(), keys)
            _remaining(deadline)
            self._sets.move_to_end(jwks_uri)
            while len(self._sets) > _MAX_JWKS_CACHE:
                self._sets.popitem(last=False)
        except TimeoutError:
            raise
        except Exception as exc:
            raise HostGrantDecodeError("Host Grant signing key prefetch failed") from exc
        finally:
            self._lock.release()

    def _fetch(self, uri: str, deadline: float) -> PyJWKSet:
        if not uri.startswith("https://"):
            raise ValueError("JWKS URI must be registry-pinned HTTPS")
        remaining = _remaining(deadline)
        # ponytail: libc DNS and urllib are blocking. A short cache-miss child is
        # terminated/reaped, not abandoned like a timed-out executor thread.
        child = subprocess.Popen(
            [sys.executable, "-c", _FETCH_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            output, _ = child.communicate(
                json.dumps((uri, remaining, _MAX_JWKS_BYTES)).encode(),
                timeout=_remaining(deadline),
            )
            if child.returncode or len(output) > _MAX_JWKS_BYTES:
                raise ValueError("JWKS retrieval failed or exceeded its bound")
        except BaseException as exc:
            if child.poll() is None:
                with suppress(Exception):
                    child.kill()
            with suppress(Exception):
                child.communicate()
            if isinstance(exc, subprocess.TimeoutExpired):
                raise TimeoutError("Host Grant JWKS deadline exceeded") from None
            raise
        _remaining(deadline)
        data = json.loads(output)
        keys = data.get("keys") if isinstance(data, dict) else None
        if not isinstance(keys, list) or not 1 <= len(keys) <= _MAX_JWKS_KEYS:
            raise ValueError("JWKS key count exceeds its bound")
        for key in keys:
            if not isinstance(key, dict) or len(str(key.get("n", ""))) > 1366:
                raise ValueError("JWKS key exceeds its bound")
        result = PyJWKSet.from_dict(data)
        _remaining(deadline)
        return result


@dataclass(frozen=True)
class PyJwtHostGrantDecoder:
    """Decode one registry-bound token with explicit algorithm and claim pins."""

    key_resolver: JwksKeyResolver

    def decode(
        self,
        token: str,
        *,
        config: HostGrantVerificationConfig,
        deadline: float | None = None,
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
            if deadline is not None:
                _remaining(deadline)
                key = self.key_resolver.resolve(config.jwks_uri, token, deadline=deadline)
            else:
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
            if deadline is not None:
                _remaining(deadline)
        except TimeoutError:
            raise
        except Exception as exc:  # Signature, claim and model failures are one safe error.
            if isinstance(exc, HostGrantDecodeError):
                raise
            raise HostGrantDecodeError("Host Grant signature or claims are invalid") from exc
        return DecodedJwtGrant(grant=grant, algorithm=algorithm)
