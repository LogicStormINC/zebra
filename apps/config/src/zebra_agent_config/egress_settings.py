"""Operator-only numeric SOCKS endpoint for Cloud native network children."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping


def load_egress_endpoint(values: Mapping[str, str], *, profile: str) -> tuple[str, int] | None:
    raw = values.get("ZEBRA_WEB_EGRESS_SOCKS_ENDPOINT", "").strip()
    if not raw:
        return None
    if profile not in {"cloud", "production"}:
        raise ValueError("controlled egress requires a Cloud profile")
    value = json.loads(raw)
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("egress endpoint must be [numeric IP, port]")
    host, port = value
    if not isinstance(host, str) or type(port) is not int or not 0 < port < 65536:
        raise ValueError("invalid egress endpoint")
    ip = ipaddress.ip_address(host)
    if ip.is_unspecified or ip.is_multicast or getattr(ip, "scope_id", None):
        raise ValueError("invalid egress endpoint IP")
    return str(ip), port
