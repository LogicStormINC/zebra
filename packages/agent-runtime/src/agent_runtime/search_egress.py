"""Private search authority is bound to an operator endpoint, never a tool argument."""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request
from collections.abc import Sequence
from http.client import HTTPResponse

from agent_core.domain.web import parse_web_target
from agent_tools.web_gateway import WebGatewayError

from agent_runtime.mcp_http_egress import PublicMcpHttpsConnection, PublicMcpHttpsHandler
from agent_runtime.public_dns import AddressInfo, PublicAddressBlocked

_BACKEND_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


def _backend_addresses(hostname: str, port: int) -> Sequence[AddressInfo]:
    addresses: Sequence[AddressInfo] = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    ips = [ipaddress.ip_address(item[4][0]) for item in addresses]
    if not ips or any(
        ip.is_multicast
        or ip.is_reserved
        or str(ip) == "fd00:ec2::254"
        or not (ip.is_global or any(ip in net for net in _BACKEND_NETWORKS))
        for ip in ips
    ):
        raise PublicAddressBlocked("configured search backend resolves to a blocked address")
    return addresses


class _SearchBackendConnection(PublicMcpHttpsConnection):
    # Operator-bound private backend stays on its original validated private route.
    _controlled_egress = False

    def resolve_addresses(self) -> Sequence[AddressInfo]:
        # The handler is created only after exact endpoint admission below;
        # connection-time validation pins the actual DNS answer, preserving SNI.
        return _backend_addresses(self.host, self.port)


class _SearchBackendHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> HTTPResponse:
        return self.do_open(_SearchBackendConnection, req)


def search_network_options(
    url: str, trusted_endpoint: str | None, *, use_system_proxy: bool
) -> tuple[dict[str, str], urllib.request.HTTPSHandler | None]:
    from agent_runtime.web_gateway import _proxy_configuration

    target = parse_web_target(url)
    if trusted_endpoint is not None:
        expected = parse_web_target(trusted_endpoint)
        actual_parts = urllib.parse.urlsplit(target.url)
        expected_parts = urllib.parse.urlsplit(expected.url)
        # Search adds q/format/limit but cannot change the configured URL path,
        # origin, or fixed query parameters. Redirects are independently refused.
        expected_query = urllib.parse.parse_qs(expected_parts.query)
        actual_query = urllib.parse.parse_qs(actual_parts.query)
        if actual_parts[:3] != expected_parts[:3] or any(
            actual_query.get(k) != v for k, v in expected_query.items()
        ):
            raise WebGatewayError(
                "search endpoint differs from operator configuration",
                reason="private_network_blocked",
            )
        try:
            _backend_addresses(target.hostname, 443)
        except PublicAddressBlocked as exc:
            raise WebGatewayError(str(exc), reason="private_network_blocked") from exc
        except OSError as exc:
            raise WebGatewayError("search backend resolution unavailable") from exc
        return {}, _SearchBackendHandler()
    proxies = _proxy_configuration(target.hostname, use_system_proxy=use_system_proxy)
    return proxies, None if proxies else PublicMcpHttpsHandler()
