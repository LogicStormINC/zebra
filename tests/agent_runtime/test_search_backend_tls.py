"""Real socket/TLS acceptance, with only scratch address routing substituted."""

import io
import json
import socket
from dataclasses import asdict
from unittest.mock import Mock

import pytest
from agent_core.domain.web import parse_web_target
from agent_runtime.harness import LocalToolGateway
from agent_runtime.search_egress import _SearchBackendConnection
from agent_runtime.web_gateway import _network_child
from agent_tools.web_search import WebSearchRequest

from tests.agent_runtime.test_crawl_source_http import call, native_tls_source


def test_search_backend_socket_is_pinned_and_tls_keeps_origin(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("172.20.0.2", 443))]
    )
    sock = Mock()
    monkeypatch.setattr(socket, "socket", lambda *a: sock)
    context = Mock()
    connection = _SearchBackendConnection("search.zebra.test", timeout=2, context=context)
    connection.connect()
    sock.connect.assert_called_once_with(("172.20.0.2", 443))
    context.wrap_socket.assert_called_once_with(sock, server_hostname="search.zebra.test")


@pytest.mark.parametrize("operation", ["search", "search_json"])
@pytest.mark.parametrize("trusted", [True, False])
def test_native_protocol_preserves_trusted_search_tls(
    tmp_path, monkeypatch, capsys, operation, trusted
):
    endpoint = "https://source.example/search"
    with native_tls_source(tmp_path, monkeypatch, "normal", trusted=trusted) as (
        requests,
        _,
        _,
        _,
        _,
    ):
        # This isolated fixture substitutes only the scratch server's sockaddr;
        # body, URL checks, TLS/SAN/CA, normalization and child dispatch are real.
        from agent_runtime.mcp_http_egress import PublicMcpHttpsConnection

        def scratch_addresses(hostname, port):
            assert (hostname, port) == ("source.example", 443)
            return PublicMcpHttpsConnection.resolve_addresses(None)

        monkeypatch.setattr("agent_runtime.search_egress._backend_addresses", scratch_addresses)
        arguments = (
            asdict(WebSearchRequest("call", parse_web_target(endpoint), "zebra", 2))
            if operation == "search"
            else endpoint + "?q=zebra&format=json"
        )
        monkeypatch.setattr(
            "sys.stdin", io.StringIO(json.dumps((operation, arguments, False, 65536, endpoint)))
        )
        _network_child()
        output = json.loads(capsys.readouterr().out)
        if trusted:
            assert "error" not in output
            assert requests and requests[0].startswith("/search?")
        else:
            assert "error" in output and not requests


@pytest.mark.parametrize("v2", [False, True])
def test_both_gateway_registrations_bind_the_operator_endpoint(tmp_path, monkeypatch, v2):
    seen = []
    endpoint = "https://search.zebra.test/search"
    if v2:

        class Provider:
            name = "searxng"
            available = True

            def __init__(self, **options):
                seen.append(options["trusted_search_endpoint"])

            def search(self, query, *, limit):
                return ()

        monkeypatch.setattr("agent_runtime.web_tools.SearXNGSearchProvider", Provider)
    else:
        from agent_tools.web_search import WebSearchResponse

        class Transport:
            def __init__(self, **options):
                seen.append(options["trusted_search_endpoint"])

            def execute(self, request):
                return WebSearchResponse((), "searxng", 15, {})

        monkeypatch.setattr("agent_runtime.harness.LocalWebSearchTransport", Transport)
    gateway = LocalToolGateway(
        tmp_path,
        trusted_local=False,
        web_pipeline_v2=v2,
        web_search_endpoint=endpoint,
        web_search_private_backend=True,
    )
    try:
        assert gateway.execute(call("web.search", query="zebra")).status.value == "executed"
        assert seen == [endpoint]
    finally:
        gateway.close()
