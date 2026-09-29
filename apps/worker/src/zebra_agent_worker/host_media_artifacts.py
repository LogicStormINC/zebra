"""Materialize an authority-scoped Host media envelope as a Session Artifact."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_security.ssrf import HostNameResolver, SsrfError, resolve_and_validate
from agent_tools.builtin.publish import FilePublisher

_ENVELOPE_KEY = "zebra_artifact_import"
_MEDIA_TYPES = ("image/", "video/")
_MAX_NAME = 160
_FAKE_IP_V4 = ipaddress.ip_network("198.18.0.0/15")


class HostMediaArtifactError(ValueError):
    """A bounded media envelope or transfer failed validation."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(slots=True)
class HostMediaArtifactImporter:
    publish: FilePublisher
    max_bytes: int
    resolver: HostNameResolver | None = None
    client: httpx.Client | None = None
    allow_fake_ip_dns: bool = False

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")

    def materialize(self, result: ToolResult) -> ToolResult:
        if result.status is not ToolCallStatus.EXECUTED:
            return result
        envelope = _import_envelope(result.output)
        if envelope is None:
            return result
        try:
            url, kind, requested_name, alt = _validate_envelope(
                envelope,
                self.resolver,
                allow_fake_ip_dns=self.allow_fake_ip_dns,
            )
            payload, mime_type = self._download(url, kind)
            file_name = _file_name(requested_name, url, mime_type)
            artifact_uri = self.publish(payload, file_name, mime_type)
        except HostMediaArtifactError as exc:
            return result.model_copy(
                update={
                    "status": ToolCallStatus.FAILED,
                    "output": f"Host media import failed: {exc.reason}",
                    "metadata": {
                        **result.metadata,
                        "reason": exc.reason,
                        "host_media_import": True,
                    },
                }
            )
        output = json.dumps(
            {
                "status": "ready",
                "artifact_uri": artifact_uri,
                "media_kind": kind,
                "mime_type": mime_type,
                "display_name": file_name,
                "alt": alt,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return result.model_copy(
            update={
                "output": output,
                "metadata": {
                    **result.metadata,
                    "artifact_uri": artifact_uri,
                    "delivery": True,
                    "file_name": file_name,
                    "mime_type": mime_type,
                    "media_kind": kind,
                    "alt": alt,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "host_media_import": True,
                },
            }
        )

    def _download(self, url: str, expected_kind: str) -> tuple[bytes, str]:
        client = self.client or httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))
        close_client = self.client is None
        try:
            with client.stream(
                "GET",
                url,
                headers={
                    "Accept": "image/*,video/*",
                    "User-Agent": "Zebra-Agent-Host-Media/1.0",
                },
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise HostMediaArtifactError(
                        "redirects are not allowed", reason="redirect_blocked"
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    raise HostMediaArtifactError("media request failed", reason="http_error")
                mime_type = (
                    response.headers.get("content-type", "").partition(";")[0].strip().lower()
                )
                if not mime_type.startswith(_MEDIA_TYPES) or not mime_type.startswith(
                    f"{expected_kind}/"
                ):
                    raise HostMediaArtifactError(
                        "response MIME does not match the selected media kind",
                        reason="unsupported_content_type",
                    )
                length = response.headers.get("content-length")
                if length is not None and int(length) > self.max_bytes:
                    raise HostMediaArtifactError(
                        "media exceeds the byte limit", reason="response_too_large"
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_bytes:
                        raise HostMediaArtifactError(
                            "media exceeds the byte limit", reason="response_too_large"
                        )
                if not body:
                    raise HostMediaArtifactError("media response is empty", reason="empty_response")
                return bytes(body), mime_type
        except HostMediaArtifactError:
            raise
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise HostMediaArtifactError("media transfer failed", reason="transport_error") from exc
        finally:
            if close_client:
                client.close()


def has_host_media_envelope(result: ToolResult) -> bool:
    return _import_envelope(result.output) is not None


def _import_envelope(output: str) -> Mapping[str, object] | None:
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    envelope = payload.get(_ENVELOPE_KEY)
    return envelope if isinstance(envelope, Mapping) else None


def _validate_envelope(
    envelope: Mapping[str, object],
    resolver: HostNameResolver | None,
    *,
    allow_fake_ip_dns: bool,
) -> tuple[str, str, str, str]:
    url = _required_text(envelope.get("url"), "url", maximum=2_048)
    kind = _required_text(envelope.get("media_kind"), "media_kind", maximum=16).lower()
    if kind not in {"image", "video"}:
        raise HostMediaArtifactError("unsupported media kind", reason="unsupported_media_kind")
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HostMediaArtifactError("media URL must use HTTPS", reason="ssrf_blocked")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise HostMediaArtifactError("media URL is not safe", reason="ssrf_blocked")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise HostMediaArtifactError("IP literals are not allowed", reason="ssrf_blocked")
    try:
        resolve_and_validate(parsed.hostname, resolver=resolver)
    except SsrfError as exc:
        if not (
            allow_fake_ip_dns
            and exc.reason == "private_address_blocked"
            and _only_fake_ip_addresses(parsed.hostname, resolver)
        ):
            raise HostMediaArtifactError("media hostname is not public", reason=exc.reason) from exc
        # ponytail: trusted-local Clash/Mihomo fake-IP mode only. Production
        # must use public DNS or a pinned egress proxy rather than widening SSRF.
    except OSError as exc:
        raise HostMediaArtifactError(
            "media hostname could not be resolved", reason="dns_resolution_failed"
        ) from exc
    name = _optional_text(envelope.get("display_name"), maximum=_MAX_NAME)
    alt = _optional_text(envelope.get("alt"), maximum=512)
    return url, kind, name, alt


def _only_fake_ip_addresses(hostname: str, resolver: HostNameResolver | None) -> bool:
    raw = (
        resolver(hostname)
        if resolver is not None
        else tuple({item[4][0] for item in socket.getaddrinfo(hostname, None)})
    )
    try:
        addresses = tuple(ipaddress.ip_address(value) for value in raw)
    except ValueError:
        return False
    return bool(addresses) and all(
        isinstance(address, ipaddress.IPv4Address) and address in _FAKE_IP_V4
        for address in addresses
    )


def _file_name(requested: str, url: str, mime_type: str) -> str:
    candidate = requested or unquote(PurePosixPath(urlsplit(url).path).name)
    candidate = re.sub(r"[^\w. -]+", "-", candidate, flags=re.UNICODE).strip(" .-")
    suffix = mimetypes.guess_extension(mime_type) or (".jpg" if mime_type == "image/jpeg" else "")
    if not candidate:
        candidate = f"host-media{suffix}"
    elif not PurePosixPath(candidate).suffix and suffix:
        candidate = f"{candidate}{suffix}"
    return candidate[:_MAX_NAME]


def _required_text(value: object, field: str, *, maximum: int) -> str:
    text = _optional_text(value, maximum=maximum)
    if not text:
        raise HostMediaArtifactError(f"{field} is required", reason="invalid_envelope")
    return text


def _optional_text(value: object, *, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HostMediaArtifactError("media envelope text is invalid", reason="invalid_envelope")
    text = value.strip()
    if len(text) > maximum or any(ord(char) < 32 for char in text):
        raise HostMediaArtifactError(
            "media envelope text is outside its bounds", reason="invalid_envelope"
        )
    return text
