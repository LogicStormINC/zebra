import socket

import pytest
from agent_core.domain.web import parse_web_target
from agent_tools.web_search import WebSearchRequest

ENDPOINT = "https://search.zebra.test/search"


def test_operator_search_backend_can_use_private_tls_socket(monkeypatch):
    from agent_runtime.search_egress import search_network_options
    from agent_runtime.web_gateway import _NoRedirectHandler

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("172.20.0.2", 443))]
    )
    proxies, handler = search_network_options(ENDPOINT, ENDPOINT, use_system_proxy=False)
    assert proxies == {}
    assert handler is not None
    assert (
        _NoRedirectHandler().redirect_request(None, None, 302, "", {}, "https://evil.test") is None
    )


@pytest.mark.parametrize(
    "url",
    ["https://other.zebra.test/search", ENDPOINT + "/other", "https://search.zebra.test/admin"],
)
def test_private_exception_cannot_escape_configured_endpoint(monkeypatch, url):
    from agent_runtime.search_egress import search_network_options
    from agent_tools.web_gateway import WebGatewayError

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("172.20.0.2", 443))]
    )
    with pytest.raises(WebGatewayError):
        search_network_options(url, ENDPOINT, use_system_proxy=False)


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "169.254.169.254", "198.18.0.1", "0.0.0.0", "224.0.0.1", "fd00:ec2::254"]
)
def test_even_trusted_backend_rejects_metadata_loopback_and_fake_ip(monkeypatch, ip):
    from agent_runtime.search_egress import search_network_options
    from agent_tools.web_gateway import WebGatewayError

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (ip, 443))])
    with pytest.raises(WebGatewayError):
        search_network_options(ENDPOINT, ENDPOINT, use_system_proxy=False)


def test_native_child_retains_fixed_backend_authority(monkeypatch):
    from agent_runtime.web_search import LocalWebSearchTransport

    seen = {}

    def child(operation, arguments, check, **options):
        seen.update(options)
        return {"results": [], "provider": "searxng", "byte_count": 15, "metadata": {}}

    monkeypatch.setattr("agent_runtime.web_search._native_network_call", child)
    LocalWebSearchTransport(
        trusted_search_endpoint=ENDPOINT, network_cancellation_check=lambda: None
    ).execute(WebSearchRequest("call", parse_web_target(ENDPOINT), "zebra", 2))
    assert seen["trusted_search_endpoint"] == ENDPOINT
