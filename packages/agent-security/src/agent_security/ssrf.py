"""Runtime SSRF guards for web egress.

``parse_web_target`` enforces the *parse-time* URL contract (https-only, no
user info, no explicit port, public hostname, no IP literal). This module
closes the *runtime* gap: a public-looking hostname can still resolve, after
DNS, to a private / link-local / loopback address (DNS rebinding), or redirect
to one. Every outbound web request must validate resolved addresses here, and
every redirect must be re-validated.

The resolver is injectable so tests are fully deterministic and offline.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

HostNameResolver = Callable[[str], tuple[str, ...]]

#: Maximum redirect hops before the chain is rejected.
DEFAULT_MAX_REDIRECTS = 5

#: Cloud instance metadata endpoints. All are link-local (169.254.0.0/16) so
#: ``ip_address(...).is_link_local`` already catches them, but we list them for
#: documentation and explicit deny-listing.
CLOUD_METADATA_HOSTNAMES = frozenset(
    {
        "metadata.google.internal",
        "169.254.169.254",
        "metadata.azure.com",
        "fd00:ec2::254",
    }
)


class SsrfError(ValueError):
    """Raised when a runtime web target resolves to a disallowed address."""

    def __init__(self, message: str, *, reason: str = "ssrf_blocked") -> None:
        super().__init__(message)
        self.reason = reason


def is_disallowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for loopback, private, link-local, multicast, reserved,
    unspecified, or zero-scope addresses. Cloud metadata (169.254.x) is
    link-local and therefore covered."""
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _resolve_with_resolver(
    hostname: str,
    *,
    resolver: HostNameResolver | None,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    if resolver is not None:
        raw_addresses = resolver(hostname)
    else:
        raw_addresses = _default_resolver(hostname)
    parsed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw in raw_addresses:
        try:
            parsed.append(ipaddress.ip_address(raw))
        except ValueError as exc:
            raise SsrfError(
                f"hostname {hostname!r} resolved to a non-IP value",
                reason="dns_resolution_invalid",
            ) from exc
    if not parsed:
        raise SsrfError(
            f"hostname {hostname!r} did not resolve to any address",
            reason="dns_resolution_empty",
        )
    return tuple(parsed)


def _default_resolver(hostname: str) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SsrfError(
            f"hostname {hostname!r} could not be resolved",
            reason="dns_resolution_failed",
        ) from exc
    seen: list[str] = []
    for info in infos:
        ip = info[4][0]
        if isinstance(ip, str) and ip not in seen:
            seen.append(ip)
    return tuple(seen)


def resolve_and_validate(
    hostname: str,
    *,
    resolver: HostNameResolver | None = None,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    """Resolve ``hostname`` and reject if ANY resolved address is disallowed.

    Returns the pinned, validated addresses. Callers MUST connect to one of
    these addresses directly (not re-resolve) to defeat DNS rebinding.
    """
    if hostname.lower() in CLOUD_METADATA_HOSTNAMES:
        raise SsrfError(
            f"hostname {hostname!r} is a known cloud metadata endpoint",
            reason="cloud_metadata_blocked",
        )
    addresses = _resolve_with_resolver(hostname, resolver=resolver)
    for address in addresses:
        if is_disallowed_address(address):
            raise SsrfError(
                f"hostname {hostname!r} resolves to disallowed address {address}",
                reason="private_address_blocked",
            )
    return addresses


@dataclass(frozen=True)
class RedirectBudget:
    """Track redirect depth and enforce re-validation on every hop."""

    max_redirects: int = DEFAULT_MAX_REDIRECTS
    followed: int = 0

    def __post_init__(self) -> None:
        if self.max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        if self.followed < 0:
            raise ValueError("followed must not be negative")

    def next(self, *, from_url: str, to_url: str) -> RedirectBudget:
        if self.followed >= self.max_redirects:
            raise SsrfError(
                f"redirect chain exceeded {self.max_redirects} hops",
                reason="redirect_limit_exceeded",
            )
        target = urlsplit(to_url)
        if target.scheme.lower() not in {"https"}:
            raise SsrfError(
                "redirect target must use https",
                reason="redirect_scheme_blocked",
            )
        if target.username is not None or target.password is not None:
            raise SsrfError(
                "redirect target must not contain user information",
                reason="redirect_userinfo_blocked",
            )
        return RedirectBudget(max_redirects=self.max_redirects, followed=self.followed + 1)


@dataclass
class CompressionRatioGuard:
    """Block decompression bombs: a small wire payload that explodes when decoded."""

    max_ratio: int

    def __post_init__(self) -> None:
        if self.max_ratio <= 0:
            raise ValueError("max_ratio must be positive")

    def observe(self, *, wire_bytes: int, decoded_bytes: int) -> None:
        if wire_bytes < 0 or decoded_bytes < 0:
            raise ValueError("byte counts must not be negative")
        if wire_bytes == 0:
            return
        ratio = decoded_bytes / wire_bytes
        if ratio > self.max_ratio:
            raise SsrfError(
                f"decompressed payload ratio {ratio:.1f} exceeds limit {self.max_ratio}",
                reason="compression_ratio_exceeded",
            )
