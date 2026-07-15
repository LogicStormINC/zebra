from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit


class WebTargetError(ValueError):
    """Raised when a Web target is outside the bounded HTTPS contract."""


@dataclass(frozen=True)
class WebTarget:
    url: str
    hostname: str


def parse_web_target(value: object) -> WebTarget:
    if not isinstance(value, str) or not value.strip():
        raise WebTargetError("web URL must be a non-blank string")
    raw_url = value.strip()
    if any(ord(character) <= 32 or ord(character) == 127 for character in raw_url):
        raise WebTargetError("web URL must not contain spaces or control characters")
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise WebTargetError("web URL is malformed") from exc
    if parsed.scheme.lower() != "https":
        raise WebTargetError("web URL must use https")
    if parsed.username is not None or parsed.password is not None:
        raise WebTargetError("web URL must not contain user information")
    if port is not None:
        raise WebTargetError("web URL must not contain an explicit port")
    if parsed.fragment:
        raise WebTargetError("web URL must not contain a fragment")
    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname == "localhost" or hostname.endswith(".localhost"):
        raise WebTargetError("web URL must use a public hostname")
    try:
        ip_address(hostname)
    except ValueError:
        pass
    else:
        raise WebTargetError("web URL must not use an IP address")
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise WebTargetError("web URL hostname is invalid") from exc
    if len(ascii_hostname) > 253 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in ascii_hostname.split(".")
    ):
        raise WebTargetError("web URL hostname is invalid")
    normalized_url = urlunsplit(
        ("https", ascii_hostname, parsed.path or "/", parsed.query, "")
    )
    return WebTarget(url=normalized_url, hostname=ascii_hostname)
