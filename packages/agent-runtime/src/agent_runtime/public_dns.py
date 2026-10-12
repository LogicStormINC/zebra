"""Bounded Fake-IP recovery, without authorizing a connection to reserved IPs."""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Any

from agent_tools.web_gateway import WebGatewayError

AddressInfo = tuple[int, int, int, str, tuple[Any, ...]]
_FAKE_IP = ipaddress.ip_network("198.18.0.0/15")


class PublicAddressBlocked(OSError):
    """Resolved address is forbidden, unlike transient DNS transport failures."""


def public_addresses(hostname: str, port: int) -> Sequence[AddressInfo]:
    answers: Sequence[AddressInfo] = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    ips = [ipaddress.ip_address(item[4][0]) for item in answers]
    if ips and all(ip in _FAKE_IP for ip in ips):
        # ponytail: only A answers on Fake-IP fallback; native public DNS keeps
        # its IPv6 sockaddr. An operator egress resolver is the fleet upgrade.
        resolved = _doh_addresses(hostname)
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in resolved]
        ips = [ipaddress.ip_address(ip) for ip in resolved]
    if not ips or any(not ip.is_global or ip.is_multicast or ip.is_reserved for ip in ips):
        raise PublicAddressBlocked("target resolves to a blocked address")
    return answers


def public_host_ips(hostname: str) -> tuple[str, ...]:
    try:
        return tuple(item[4][0] for item in public_addresses(hostname, 443))
    except PublicAddressBlocked as exc:
        raise WebGatewayError(str(exc), reason="private_network_blocked") from exc
    except OSError as exc:
        raise WebGatewayError("public DNS resolution unavailable") from exc


class _NoDnsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _doh_addresses(hostname: str) -> tuple[str, ...]:
    query = urllib.parse.urlencode({"name": hostname, "type": "A"})
    request = urllib.request.Request(
        f"https://1.1.1.1/dns-query?{query}", headers={"Accept": "application/dns-json"}
    )
    # Literal public resolver IP, verified TLS, no env proxy or redirects.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoDnsRedirect())
    try:
        with opener.open(request, timeout=3) as response:
            if response.status != 200:
                raise OSError("public DNS response failed")
            body = response.read(65_537)
        if len(body) > 65_536:
            raise OSError("public DNS response exceeded bound")
        payload = json.loads(body)
        if not isinstance(payload, dict) or payload.get("Status") != 0:
            raise OSError("public DNS resolution failed")
        questions = payload.get("Question", [])
        if (
            not isinstance(questions, list)
            or len(questions) != 1
            or not isinstance(questions[0], dict)
            or questions[0].get("type") != 1
            or str(questions[0].get("name", "")).rstrip(".").lower() != hostname.rstrip(".").lower()
        ):
            raise OSError("public DNS question mismatch")
        answers = payload.get("Answer", [])
        if not isinstance(answers, list):
            raise OSError("invalid public DNS answers")
        return tuple(
            str(ipaddress.IPv4Address(item["data"]))
            for item in answers
            if isinstance(item, dict)
            and item.get("type") == 1
            and isinstance(item.get("data"), str)
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise OSError("invalid public DNS response") from exc
