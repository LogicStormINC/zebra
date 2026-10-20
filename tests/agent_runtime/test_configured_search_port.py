"""Operator-bound ports must not expand model-controlled web authority."""

import socket

import pytest
from agent_core.domain.web import WebTargetError, parse_web_target
from agent_runtime.search_egress import search_network_options
from agent_runtime.web_tools import optional_web_search_endpoint
from agent_security.mcp_proxy_policy import ToolEgressRoute, classify_tool_egress
from agent_security.network_profile import NetworkProfile, NetworkProfileName
from agent_tools.web_gateway import WebGatewayError

from tests.agent_runtime.test_crawl_source_http import call

ENDPOINT = "https://search.zebra.test:18445/search"


def test_configured_private_port_is_retained_and_admitted(monkeypatch):
    target = optional_web_search_endpoint(ENDPOINT, private_backend=True)
    assert target.url == ENDPOINT
    ports = []

    def resolve(host, port, **options):
        ports.append(port)
        return [(2, 1, 6, "", ("192.168.160.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    assert search_network_options(ENDPOINT + "?q=NBOPC", ENDPOINT, use_system_proxy=False)[1]
    assert ports == [18445]
    search = call("web.search", query="NBOPC")
    assert (
        classify_tool_egress(
            search,
            web_search_endpoint=ENDPOINT,
            network_profile=NetworkProfile(name=NetworkProfileName.FULL_GATEWAY),
        ).route
        is ToolEgressRoute.WEB_GATEWAY
    )
    assert (
        classify_tool_egress(search, web_search_endpoint=ENDPOINT).route is ToolEgressRoute.BLOCKED
    )


@pytest.mark.parametrize("endpoint", [ENDPOINT, ENDPOINT.replace(":18445", ":0")])
def test_public_web_still_rejects_explicit_ports(endpoint):
    with pytest.raises(WebTargetError):
        parse_web_target(endpoint)
    with pytest.raises(ValueError):
        optional_web_search_endpoint(endpoint)


def test_invalid_configured_search_never_silently_disappears():
    with pytest.raises(ValueError, match="web_search_endpoint"):
        optional_web_search_endpoint("http://search.zebra.test/search", private_backend=True)
    assert optional_web_search_endpoint(None) is None


@pytest.mark.parametrize(
    "url",
    [
        ENDPOINT.replace(":18445", ":443"),
        ENDPOINT.replace("/search", "/admin"),
        ENDPOINT.replace("search.zebra.test", "other.test"),
    ],
)
def test_trusted_port_does_not_allow_other_origins_or_paths(url):
    with pytest.raises(WebGatewayError):
        search_network_options(url, ENDPOINT, use_system_proxy=False)
