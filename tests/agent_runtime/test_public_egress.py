"""No model: controlled numeric-IP transport and Cloud-only admission."""

import socket
from unittest.mock import Mock

import pytest


def test_private_target_never_contacts_control_endpoint():
    from agent_runtime.public_egress import connect_address, current_public_egress

    token = current_public_egress.set(("127.0.0.1", 1080))
    try:
        with pytest.raises(OSError, match="public"):
            connect_address(
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)), timeout=1
            )
    finally:
        current_public_egress.reset(token)


def test_cloud_endpoint_config_is_explicit_and_numeric():
    from zebra_agent_config.egress_settings import load_egress_endpoint

    assert load_egress_endpoint({}, profile="local") is None
    value = {"ZEBRA_WEB_EGRESS_SOCKS_ENDPOINT": '["127.0.0.1",1080]'}
    assert load_egress_endpoint(value, profile="cloud") == ("127.0.0.1", 1080)
    assert load_egress_endpoint(value, profile="production") == ("127.0.0.1", 1080)
    with pytest.raises(ValueError, match="Cloud"):
        load_egress_endpoint(value, profile="local")
    for raw in (
        '["proxy.example",1080]',
        '["127.0.0.1",true]',
        '["127.0.0.1",0]',
        '["127.0.0.1",65536]',
        '["0.0.0.0",80]',
        '["224.0.0.1",80]',
        "{}",
    ):
        with pytest.raises(ValueError):
            load_egress_endpoint({"ZEBRA_WEB_EGRESS_SOCKS_ENDPOINT": raw}, profile="cloud")


def test_relay_family_is_independent_of_fresh_target_family(monkeypatch):
    from agent_runtime.public_egress import connect_address, current_public_egress

    sock = Mock()
    # A fragmented SOCKS greeting/reply, with an IPv4 bound address.
    chunks = iter([b"\x05", b"\x00", b"\x05\x00", b"\x00\x01", b"\0" * 6])
    sock.recv.side_effect = lambda size: next(chunks)
    factory = Mock(return_value=sock)
    monkeypatch.setattr(socket, "socket", factory)
    token = current_public_egress.set(("127.0.0.1", 1080))
    try:
        address = "2606:4700:4700::1111"
        result = connect_address(
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0)), timeout=1
        )
        assert result is sock
        factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM, 6)
        sock.connect.assert_called_once_with(("127.0.0.1", 1080))
        assert sock.sendall.call_args_list[-1].args[0] == (
            b"\x05\x01\x00\x04" + socket.inet_pton(socket.AF_INET6, address) + b"\x01\xbb"
        )
    finally:
        current_public_egress.reset(token)


@pytest.mark.parametrize(
    "chunks",
    [
        [b"\x04\x00"],
        [b"\x05\x02"],
        [b""],
        [b"\x05\x00", b""],
        [b"\x05\x00", b"\x05\x03\x00\x01"],
        [b"\x05\x00", b"\x05\x00\x01\x01"],
        [b"\x05\x00", b"\x05\x00\x00\xff"],
        [b"\x05\x00", b"\x05\x00\x00\x03", b"\x00"],
    ],
)
def test_bad_relay_response_closes_once_without_fallback(monkeypatch, chunks):
    from agent_runtime.public_egress import connect_address, current_public_egress

    sock = Mock()
    sock.recv.side_effect = chunks
    factory = Mock(return_value=sock)
    monkeypatch.setattr(socket, "socket", factory)
    token = current_public_egress.set(("127.0.0.1", 1080))
    try:
        with pytest.raises(OSError):
            connect_address(
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)), timeout=1
            )
        sock.close.assert_called_once()
        sock.connect.assert_called_once_with(("127.0.0.1", 1080))
        assert factory.call_count == 1
    finally:
        current_public_egress.reset(token)


def test_fragmented_relay_obeys_one_deadline(monkeypatch):
    import agent_runtime.public_egress as egress

    sock = Mock()
    sock.recv.return_value = b"\x05"
    monkeypatch.setattr(socket, "socket", Mock(return_value=sock))
    clock = iter([0, 0.1, 0.2, 1.1])
    monkeypatch.setattr(egress, "monotonic", lambda: next(clock))
    token = egress.current_public_egress.set(("127.0.0.1", 1080))
    try:
        with pytest.raises(TimeoutError):
            egress.connect_address(
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)), timeout=1
            )
        sock.close.assert_called_once()
        assert sock.recv.call_count == 1
    finally:
        egress.current_public_egress.reset(token)


def test_private_search_keeps_original_pinned_route(monkeypatch):
    from agent_runtime.public_egress import current_public_egress
    from agent_runtime.search_egress import _SearchBackendConnection

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", 443))],
    )
    raw = Mock()
    monkeypatch.setattr(socket, "socket", Mock(return_value=raw))
    context = Mock()
    token = current_public_egress.set(("127.0.0.1", 1080))
    try:
        _SearchBackendConnection("internal.example", timeout=1, context=context).connect()
        raw.connect.assert_called_once_with(("192.168.1.2", 443))
        raw.sendall.assert_not_called()
        context.wrap_socket.assert_called_once_with(raw, server_hostname="internal.example")
    finally:
        current_public_egress.reset(token)


def test_routed_tls_and_fresh_dns_are_not_delegated(monkeypatch):
    import ssl

    from agent_runtime.mcp_http_egress import PublicMcpHttpsConnection
    from agent_runtime.public_egress import current_public_egress
    from agent_runtime.web_gateway import _proxy_configuration

    resolver = Mock(
        side_effect=[
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ]
    )
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    raw = Mock()
    raw.recv.side_effect = [b"\x05\x00", b"\x05\x00\x00\x01", b"\0" * 6]
    factory = Mock(return_value=raw)
    monkeypatch.setattr(socket, "socket", factory)
    context = Mock()
    context.wrap_socket.side_effect = ssl.SSLCertVerificationError("invalid cert")
    token = current_public_egress.set(("127.0.0.1", 1080))
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.example:8080")
    try:
        assert _proxy_configuration("source.example", use_system_proxy=True) == {}
        with pytest.raises(ssl.SSLCertVerificationError):
            PublicMcpHttpsConnection("source.example", timeout=1, context=context).connect()
        context.wrap_socket.assert_called_once_with(raw, server_hostname="source.example")
        raw.close.assert_called_once()
        with pytest.raises(OSError, match="blocked"):
            PublicMcpHttpsConnection("source.example", timeout=1, context=context).connect()
        assert factory.call_count == 1 and resolver.call_count == 2
    finally:
        current_public_egress.reset(token)


def test_worker_readiness_precedes_claim_or_provider(monkeypatch):
    import importlib
    from dataclasses import replace

    from zebra_agent_config import load_settings

    module = importlib.import_module("zebra_agent_worker.main")
    settings = replace(
        load_settings(env={}), profile="cloud", web_egress_socks_endpoint=("127.0.0.1", 1080)
    )
    monkeypatch.setattr(module, "load_settings", lambda: settings)
    probe = Mock(side_effect=OSError("relay offline"))
    monkeypatch.setattr(module, "probe_egress", probe)
    loop = Mock()
    monkeypatch.setattr(module, "build_worker_loop_service", loop)
    with pytest.raises(OSError, match="relay offline"):
        module.main(["--max-cycles", "0"])
    probe.assert_called_once_with(settings.web_egress_socks_endpoint)
    loop.assert_not_called()


def test_startup_probe_reaches_remote_channel_and_restores_context(monkeypatch):
    from agent_runtime import public_egress as egress

    raw = Mock()
    raw.recv.side_effect = [b"\x05\x00", b"\x05\x00\x00\x01", b"\0" * 6]
    monkeypatch.setattr(socket, "socket", Mock(return_value=raw))
    egress.probe_egress(("127.0.0.1", 1080))
    assert egress.current_public_egress.get() is None
    assert raw.sendall.call_args_list[-1].args[0] == b"\x05\x01\x00\x01\x01\x01\x01\x01\x01\xbb"


def test_worker_gateway_composes_route_only_for_cloud(monkeypatch, tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace

    from agent_core.domain.identifiers import new_session_id
    from agent_core.domain.tool_profiles import ToolProfile
    from agent_runtime import LocalToolGateway
    from agent_security import DEFAULT_NETWORK_PROFILE
    from zebra_agent_config import load_settings
    from zebra_agent_worker.tool_gateway_runtime import build_worker_tool_gateway

    for profile in ("local", "cloud", "production"):
        settings = replace(
            load_settings(env={}), profile=profile, web_egress_socks_endpoint=("127.0.0.1", 1080)
        )
        task = SimpleNamespace(
            workspace_root=tmp_path,
            tool_profile=ToolProfile.GENERAL,
            mcp_allowlist=(),
            history_session_ids=(),
            host_context=None,
            network_profile=DEFAULT_NETWORK_PROFILE,
        )
        seen = []

        def local(*args, seen=seen, **kwargs):
            seen.append(kwargs)
            return Mock(spec=LocalToolGateway)

        monkeypatch.setattr("zebra_agent_worker.tool_gateway_runtime.LocalToolGateway", local)
        gateway = build_worker_tool_gateway(
            task,
            settings=settings,
            model_gateway=Mock(),
            session_history=Mock(),
            session_id=new_session_id(),
            runtime=Mock(),
            runtime_handle=None,
            local_artifacts=None,
            artifact_payload_reader=None,
            cloud_artifacts=None,
            trusted_local=False,
            network_cancellation_check=lambda: None,
        )
        assert seen[0]["egress_endpoint"] == (
            settings.web_egress_socks_endpoint if profile != "local" else None
        )
        gateway.close()
