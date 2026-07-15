from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request

from agent_tools.web_gateway import (
    WebGatewayError,
    WebGatewayRequest,
    WebGatewayResponse,
)

ALLOWED_CONTENT_TYPES = frozenset(
    {"application/json", "application/xml", "application/xhtml+xml"}
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class LocalWebGatewayTransport:
    """Bounded local adapter; production deployments should replace it with an egress proxy."""

    def execute(self, request: WebGatewayRequest) -> WebGatewayResponse:
        _reject_non_public_resolution(request.target.hostname)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )
        outbound = urllib.request.Request(
            request.target.url,
            headers={
                "Accept": "text/plain, text/html, application/json, application/xml",
                "User-Agent": "Zebra-Agent-Web-Gateway/1.0",
            },
            method="GET",
        )
        try:
            with opener.open(outbound, timeout=request.timeout_seconds) as response:
                content_type = _content_type(response.headers.get("Content-Type", ""))
                _require_textual_content(content_type)
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > request.max_bytes:
                    raise WebGatewayError(
                        "web response exceeds the byte limit", reason="response_too_large"
                    )
                body = response.read(request.max_bytes + 1)
                if len(body) > request.max_bytes:
                    raise WebGatewayError(
                        "web response exceeds the byte limit", reason="response_too_large"
                    )
                charset = response.headers.get_content_charset() or "utf-8"
                text = body.decode(charset, errors="replace")
                return WebGatewayResponse(
                    text=text,
                    status_code=response.status,
                    content_type=content_type,
                    byte_count=len(body),
                    metadata={"transport": "local_https", "redirects_followed": 0},
                )
        except WebGatewayError:
            raise
        except urllib.error.HTTPError as exc:
            reason = "redirect_blocked" if 300 <= exc.code < 400 else "http_error"
            raise WebGatewayError(f"web gateway HTTP error: {exc.code}", reason=reason) from exc
        except (OSError, UnicodeError, ValueError) as exc:
            raise WebGatewayError(f"web gateway request failed: {exc}") from exc


def _reject_non_public_resolution(hostname: str) -> None:
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise WebGatewayError(f"web hostname resolution failed: {exc}") from exc
    if not addresses:
        raise WebGatewayError("web hostname did not resolve")
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise WebGatewayError(
            "web hostname resolves to a non-public address", reason="private_network_blocked"
        )


def _content_type(value: str) -> str:
    return value.partition(";")[0].strip().lower()


def _require_textual_content(content_type: str) -> None:
    if content_type.startswith("text/") or content_type in ALLOWED_CONTENT_TYPES:
        return
    raise WebGatewayError(
        f"web response content type is not textual: {content_type or 'missing'}",
        reason="unsupported_content_type",
    )
