"""Run with uv run python scripts/check_web_single_resolution.py; no network."""

import json
import socket
from unittest.mock import Mock, patch

from agent_core.domain.web import parse_web_target
from agent_runtime import public_dns
from agent_runtime.mcp_http_egress import PublicMcpHttpsConnection
from agent_runtime.search_providers import urllib_fetch_json
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_runtime.web_search import LocalWebSearchTransport
from agent_tools.web_gateway import WebGatewayError, WebGatewayRequest
from agent_tools.web_search import WebSearchRequest


def answers(*ips: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


def run() -> None:
    target = parse_web_target("https://example.test/info")
    def fetch() -> object:
        return LocalWebGatewayTransport().execute(WebGatewayRequest("check", target))

    def search() -> object:
        return LocalWebSearchTransport().execute(
            WebSearchRequest("check", target, "official release", 1)
        )

    def provider() -> object:
        return urllib_fetch_json()(target.url)
    for operation in (fetch, search, provider):
        # Real urllib handler/connect, only the socket and TLS peer are doubles.
        peer = Mock()
        peer.makefile.return_value = None
        with (
            patch.object(socket, "getaddrinfo", return_value=answers("198.18.0.1")) as dns,
            patch.object(public_dns, "_doh_addresses", return_value=("93.184.216.34",)) as doh,
            patch.object(socket, "socket") as factory,
            patch("ssl.SSLContext.wrap_socket", return_value=peer) as tls,
        ):
            # Stop after the successful TLS connection, before fake response parsing.
            peer.sendall.side_effect = OSError("peer test stop")
            for _ in range(2):
                try:
                    operation()
                except WebGatewayError as exc:
                    assert exc.reason == "gateway_unavailable"
                else:
                    raise AssertionError("transport unexpectedly succeeded")
            assert dns.call_count == doh.call_count == 2, (dns.call_count, doh.call_count)
            assert factory.call_count == 2
            assert tls.call_args.kwargs["server_hostname"] == "example.test"
            assert factory.return_value.connect.call_args.args == (("93.184.216.34", 443),)
        for ips in (("127.0.0.1",), ("93.184.216.34", "10.0.0.1")):
            with (
                patch.object(socket, "getaddrinfo", return_value=answers(*ips)),
                patch.object(socket, "socket") as factory,
            ):
                try:
                    operation()
                except WebGatewayError as exc:
                    assert exc.reason == "private_network_blocked", exc.reason
                else:
                    raise AssertionError("blocked DNS accepted")
                factory.assert_not_called()
    context = PublicMcpHttpsConnection("example.test")._context
    assert context.check_hostname and context.verify_mode.name == "CERT_REQUIRED"
    print(json.dumps({"transports": 3, "fresh_requests_each": 2, "blocked_cases": 6}))


if __name__ == "__main__":
    run()
