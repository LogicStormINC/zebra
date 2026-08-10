"""Bounded HTTP transport for the typed Host Tool Gateway."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from agent_security.ssrf import (
    HostNameResolver,
    SsrfError,
    resolve_and_validate,
)

from agent_integrations.host_tools.contracts import (
    HostToolTransportError,
    HostToolTransportResponse,
)

DEFAULT_HOST_TOOL_TIMEOUT_SECONDS = 10.0
MAX_HOST_TOOL_RESPONSE_BYTES = 4_194_304


@dataclass
class HttpHostToolTransport:
    """No-redirect HTTP transport with DNS/response bounds and injection seams."""

    resolver: HostNameResolver | None = None
    client: httpx.Client | None = None
    max_response_bytes: int = MAX_HOST_TOOL_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None,
        timeout_seconds: float,
    ) -> HostToolTransportResponse:
        _validate_endpoint(url, resolver=self.resolver)
        if timeout_seconds <= 0 or timeout_seconds > 900:
            raise HostToolTransportError("Host Tool timeout is outside its bound", reason="timeout")
        try:
            if self.client is None:
                response = httpx.request(
                    method,
                    url,
                    headers=dict(headers),
                    json=dict(body) if body is not None else None,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                )
            else:
                response = self.client.request(
                    method,
                    url,
                    headers=dict(headers),
                    json=dict(body) if body is not None else None,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                )
        except httpx.TimeoutException as exc:
            raise HostToolTransportError("Host Tool request timed out", reason="timeout") from exc
        except httpx.HTTPError as exc:
            raise HostToolTransportError(
                "Host Tool transport failed", reason="transport_error"
            ) from exc
        content = response.content
        if len(content) > self.max_response_bytes:
            raise HostToolTransportError(
                "Host Tool response exceeds its bound", reason="response_too_large"
            )
        try:
            payload: object = response.json()
        except ValueError:
            payload = response.text
        return HostToolTransportResponse(
            status_code=response.status_code,
            body=payload,
            content_type=response.headers.get("content-type", ""),
        )


def _validate_endpoint(
    url: str,
    *,
    resolver: HostNameResolver | None,
) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise HostToolTransportError("Host Tool endpoint must use HTTPS", reason="ssrf_blocked")
    if parsed.username is not None or parsed.password is not None:
        raise HostToolTransportError(
            "Host Tool endpoint must not contain credentials", reason="ssrf_blocked"
        )
    if parsed.query or parsed.fragment:
        raise HostToolTransportError(
            "Host Tool endpoint must not contain query or fragment", reason="ssrf_blocked"
        )
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise HostToolTransportError(
            "Host Tool endpoint has an invalid port", reason="ssrf_blocked"
        ) from exc
    if hostname is None:
        raise HostToolTransportError(
            "Host Tool endpoint must contain a hostname", reason="ssrf_blocked"
        )
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise HostToolTransportError(
            "Host Tool endpoint must not use an IP literal", reason="ssrf_blocked"
        )
    if port is not None and not 1 <= port <= 65_535:
        raise HostToolTransportError("Host Tool endpoint port is invalid", reason="ssrf_blocked")
    try:
        resolve_and_validate(hostname, resolver=resolver)
    except SsrfError as exc:
        raise HostToolTransportError(
            "Host Tool endpoint failed SSRF validation", reason=exc.reason
        ) from exc
