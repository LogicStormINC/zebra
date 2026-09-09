import socket
import ssl
import urllib.request
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_runtime.mcp_http_egress import PublicMcpHttpsConnection, PublicMcpHttpsHandler


def answers(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


def test_socket_uses_validated_ip_and_tls_uses_hostname(monkeypatch):
    resolver = Mock(return_value=answers("93.184.216.34"))
    sock = Mock()
    factory = Mock(return_value=sock)
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    monkeypatch.setattr(socket, "socket", factory)
    context = Mock()
    connection = PublicMcpHttpsConnection("example.test", timeout=2, context=context)
    connection.connect()
    resolver.assert_called_once_with("example.test", 443, type=socket.SOCK_STREAM)
    sock.connect.assert_called_once_with(("93.184.216.34", 443))
    sock.settimeout.assert_called_once_with(2)
    context.wrap_socket.assert_called_once_with(sock, server_hostname="example.test")


@pytest.mark.parametrize(
    "ips",
    [
        (),
        ("127.0.0.1",),
        ("169.254.169.254",),
        ("10.0.0.1",),
        ("::1",),
        ("::ffff:127.0.0.1",),
        ("93.184.216.34", "192.168.1.2"),
    ],
)
def test_blocked_dns_never_opens_socket(monkeypatch, ips):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers(*ips))
    factory = Mock()
    monkeypatch.setattr(socket, "socket", factory)
    with pytest.raises(OSError, match="blocked"):
        PublicMcpHttpsConnection("example.test", timeout=2).connect()
    factory.assert_not_called()


def test_dns_rebinding_after_preflight_is_rejected(monkeypatch):
    from agent_runtime.web_gateway import reject_non_public_resolution

    resolver = Mock(side_effect=[answers("93.184.216.34"), answers("127.0.0.1")])
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    factory = Mock()
    monkeypatch.setattr(socket, "socket", factory)
    reject_non_public_resolution("example.test")
    with pytest.raises(OSError, match="blocked"):
        PublicMcpHttpsConnection("example.test", timeout=2).connect()
    factory.assert_not_called()


@pytest.mark.parametrize("tls_failure", [False, True])
def test_failed_connection_closes_socket_without_retry(monkeypatch, tls_failure):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers("93.184.216.34"))
    sock = Mock()
    monkeypatch.setattr(socket, "socket", Mock(return_value=sock))
    context = Mock()
    if tls_failure:
        context.wrap_socket.side_effect = ssl.SSLCertVerificationError("invalid cert")
    else:
        sock.connect.side_effect = OSError("unreachable")
    with pytest.raises(OSError):
        PublicMcpHttpsConnection("example.test", timeout=2, context=context).connect()
    sock.close.assert_called_once()
    sock.connect.assert_called_once()


def test_default_tls_requires_hostname_and_certificate_validation():
    connection = PublicMcpHttpsConnection("example.test", timeout=2)
    assert connection._context.check_hostname
    assert connection._context.verify_mode == ssl.CERT_REQUIRED


def test_proxy_tunnel_rejected_before_dns(monkeypatch):
    resolver = Mock()
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    connection = PublicMcpHttpsConnection("proxy.test", timeout=2)
    connection.set_tunnel("example.test")
    with pytest.raises(OSError, match="tunnels"):
        connection.connect()
    resolver.assert_not_called()


def test_handler_routes_through_pinned_connection(monkeypatch):
    handler = PublicMcpHttpsHandler()
    do_open = Mock()
    monkeypatch.setattr(handler, "do_open", do_open)
    request = urllib.request.Request("https://example.test/mcp")
    handler.https_open(request)
    do_open.assert_called_once_with(PublicMcpHttpsConnection, request)


def test_session_disables_ambient_proxy_and_installs_pinned_handler(monkeypatch):
    from agent_runtime.mcp_http import McpHttpSession
    from agent_runtime.mcp_protocol import McpProtocolError

    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted-proxy.test:8080")
    monkeypatch.setattr(
        "agent_runtime.mcp_http.reject_non_public_resolution", lambda *a, **kw: None
    )
    opener = Mock()
    opener.open.side_effect = OSError("offline")
    build_opener = Mock(return_value=opener)
    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    server = SimpleNamespace(name="fixture", url="https://example.test/mcp", bearer_token_env=None)
    with pytest.raises(McpProtocolError, match="request failed"):
        McpHttpSession(server, 1).request("initialize")
    handlers = build_opener.call_args.args
    assert any(isinstance(handler, PublicMcpHttpsHandler) for handler in handlers)
    (proxy,) = [handler for handler in handlers if isinstance(handler, urllib.request.ProxyHandler)]
    assert proxy.proxies == {}


def test_ipv6_socket_uses_exact_validated_sockaddr(monkeypatch):
    address = ("2606:4700:4700::1111", 443, 0, 0)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", address)],
    )
    sock = Mock()
    factory = Mock(return_value=sock)
    monkeypatch.setattr(socket, "socket", factory)
    PublicMcpHttpsConnection("example.test", timeout=2, context=Mock()).connect()
    factory.assert_called_once_with(socket.AF_INET6, socket.SOCK_STREAM, 6)
    sock.connect.assert_called_once_with(address)
