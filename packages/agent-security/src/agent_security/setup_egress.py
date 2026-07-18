from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SetupEgressError(ValueError):
    """Raised when setup dependency egress cannot be proven safe."""


@dataclass
class TemporarySetupCredential:
    token_value: str | None = field(default=None, repr=False)
    revoked: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.token_value is not None and not self.token_value.strip():
            raise ValueError("temporary setup credential must not be blank")

    def authorization_header(self) -> str | None:
        if self.revoked:
            raise SetupEgressError("temporary setup credential is revoked")
        return f"Bearer {self.token_value}" if self.token_value is not None else None

    def revoke(self) -> None:
        self.token_value = None
        self.revoked = True


@dataclass(frozen=True)
class SetupDownload:
    url: str
    sha256: str
    file_name: str

    def __post_init__(self) -> None:
        digest = self.sha256.strip().lower()
        if len(digest) != 64:
            raise ValueError("setup dependency sha256 must be a digest")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("setup dependency sha256 must be hexadecimal") from exc
        name = self.file_name.strip()
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("setup dependency file_name must be a plain file name")
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "file_name", name)


@dataclass(frozen=True)
class SetupDownloadEvidence:
    url: str
    sha256: str
    file_name: str
    size_bytes: int
    cache_hit: bool


class SetupDownloadTransport(Protocol):
    def __call__(
        self,
        url: str,
        *,
        authorization: str | None,
        max_bytes: int,
    ) -> bytes: ...


class SetupEgressGateway:
    def __init__(
        self,
        *,
        allowed_domains: tuple[str, ...],
        cache_root: Path,
        credential: TemporarySetupCredential | None = None,
        max_dependency_bytes: int = 128 * 1024 * 1024,
        transport: SetupDownloadTransport | None = None,
    ) -> None:
        domains = tuple(domain.strip().lower() for domain in allowed_domains)
        if not domains or any(not domain for domain in domains):
            raise ValueError("setup egress requires non-blank allowed domains")
        for domain in domains:
            _validate_hostname(domain)
        if max_dependency_bytes <= 0:
            raise ValueError("max_dependency_bytes must be positive")
        self._allowed_domains = frozenset(domains)
        self._cache_root = cache_root.resolve(strict=False)
        self._credential = credential or TemporarySetupCredential()
        self._max_dependency_bytes = max_dependency_bytes
        self._transport = transport or _download_without_redirects
        self._closed = False

    @property
    def credential_revoked(self) -> bool:
        return self._credential.revoked

    def materialize(self, dependency: SetupDownload) -> SetupDownloadEvidence:
        if self._closed:
            raise SetupEgressError("setup egress gateway is closed")
        _validate_url(dependency.url, allowed_domains=self._allowed_domains)
        destination = self._cache_root / dependency.file_name
        if destination.is_file():
            payload = destination.read_bytes()
            if hashlib.sha256(payload).hexdigest() == dependency.sha256:
                return _evidence(dependency, payload, cache_hit=True)
        authorization = self._credential.authorization_header()
        payload = self._transport(
            dependency.url,
            authorization=authorization,
            max_bytes=self._max_dependency_bytes,
        )
        if len(payload) > self._max_dependency_bytes:
            raise SetupEgressError("setup dependency exceeds maximum size")
        actual = hashlib.sha256(payload).hexdigest()
        if actual != dependency.sha256:
            raise SetupEgressError("setup dependency sha256 mismatch")
        self._cache_root.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.write_bytes(payload)
        temporary.replace(destination)
        return _evidence(dependency, payload, cache_hit=False)

    def close(self) -> None:
        self._credential.revoke()
        self._closed = True


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _download_without_redirects(
    url: str,
    *,
    authorization: str | None,
    max_bytes: int,
) -> bytes:
    headers = {"Accept": "application/octet-stream", "User-Agent": "zebra-setup/1"}
    if authorization is not None:
        headers["Authorization"] = authorization
    request = Request(url, headers=headers, method="GET")
    try:
        with build_opener(_NoRedirects()).open(request, timeout=30) as response:
            payload = cast(bytes, response.read(max_bytes + 1))
    except HTTPError as exc:
        raise SetupEgressError(f"setup dependency download failed with HTTP {exc.code}") from exc
    return payload


def _validate_url(url: str, *, allowed_domains: frozenset[str]) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname is None:
        raise SetupEgressError("setup dependency URL must use https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupEgressError("setup dependency URL must not contain credentials or query data")
    if parsed.port not in {None, 443}:
        raise SetupEgressError("setup dependency URL must use port 443")
    hostname = parsed.hostname.lower()
    _validate_hostname(hostname)
    if hostname not in allowed_domains:
        raise SetupEgressError("setup dependency domain is not allowlisted")


def _validate_hostname(hostname: str) -> None:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("setup egress does not allow IP address targets")
    if "." not in hostname or any(part in {"", ".", ".."} for part in hostname.split(".")):
        raise ValueError("setup egress domain must be a fully qualified hostname")


def _evidence(
    dependency: SetupDownload,
    payload: bytes,
    *,
    cache_hit: bool,
) -> SetupDownloadEvidence:
    return SetupDownloadEvidence(
        url=dependency.url,
        sha256=dependency.sha256,
        file_name=dependency.file_name,
        size_bytes=len(payload),
        cache_hit=cache_hit,
    )
