import socket
from unittest.mock import Mock

import pytest
from agent_runtime.web_gateway import reject_non_public_resolution


def answers(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


def test_fake_ip_uses_public_resolution_not_fake_socket(monkeypatch):
    from agent_runtime import public_dns

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers("198.18.0.1"))
    monkeypatch.setattr(public_dns, "_doh_addresses", lambda host: ("93.184.216.34",))
    assert public_dns.public_addresses("example.com", 443)[0][4] == ("93.184.216.34", 443)
    reject_non_public_resolution("example.com")


@pytest.mark.parametrize(
    "ips",
    [
        ("10.0.0.1",),
        ("169.254.169.254",),
        ("127.0.0.1",),
        ("224.0.0.1",),
        ("198.18.0.1", "10.0.0.1"),
        ("198.18.0.1", "93.184.216.34"),
    ],
)
def test_private_or_mixed_dns_never_uses_fallback(monkeypatch, ips):
    from agent_runtime import public_dns

    fallback = Mock()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers(*ips))
    monkeypatch.setattr(public_dns, "_doh_addresses", fallback)
    with pytest.raises(OSError):
        public_dns.public_addresses("example.com", 443)
    fallback.assert_not_called()


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "198.18.0.5"])
@pytest.mark.parametrize("synthetic", ["198.18.0.1", "2001::c760:3f35"])
def test_fallback_answers_must_be_public(monkeypatch, ip, synthetic):
    from agent_runtime import public_dns

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers(synthetic))
    monkeypatch.setattr(public_dns, "_doh_addresses", lambda host: (ip,))
    with pytest.raises(OSError):
        public_dns.public_addresses("example.com", 443)


@pytest.mark.parametrize(
    "payload",
    [
        {"Status": 2},
        {"Status": 0, "Question": [{"name": "other.test", "type": 1}]},
        {"Status": 0, "Question": [{"name": "example.com", "type": 1}], "Answer": "bad"},
    ],
)
def test_doh_rejects_failure_and_wrong_question(monkeypatch, payload):
    import json

    from agent_runtime import public_dns

    from tests.agent_runtime.test_web_gateway_transport import FakeOpener, FakeResponse

    opener = FakeOpener(FakeResponse(json.dumps(payload).encode()))
    monkeypatch.setattr(public_dns.urllib.request, "build_opener", lambda *a: opener)
    with pytest.raises(OSError):
        public_dns._doh_addresses("example.com")


def test_doh_question_accepts_optional_trailing_dot(monkeypatch):
    import json

    from agent_runtime import public_dns

    from tests.agent_runtime.test_web_gateway_transport import FakeOpener, FakeResponse

    payload = {
        "Status": 0,
        "Question": [{"name": "example.com", "type": 1}],
        "Answer": [{"type": 1, "data": "93.184.216.34"}],
    }
    opener = FakeOpener(FakeResponse(json.dumps(payload).encode()))
    monkeypatch.setattr(public_dns.urllib.request, "build_opener", lambda *a: opener)
    assert public_dns._doh_addresses("example.com") == ("93.184.216.34",)


def test_doh_response_is_bounded(monkeypatch):
    from agent_runtime import public_dns

    from tests.agent_runtime.test_web_gateway_transport import FakeOpener, FakeResponse

    opener = FakeOpener(FakeResponse(b" " * 65_537))
    monkeypatch.setattr(public_dns.urllib.request, "build_opener", lambda *a: opener)
    with pytest.raises(OSError, match="bound"):
        public_dns._doh_addresses("example.com")


def test_dns_outage_is_not_reported_as_private_policy_block(monkeypatch):
    from agent_tools.web_gateway import WebGatewayError

    def unavailable(*args, **kwargs):
        raise socket.gaierror("DNS temporarily unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    with pytest.raises(WebGatewayError) as error:
        reject_non_public_resolution("example.com")
    assert error.value.reason == "gateway_unavailable"


def test_native_resolver_has_typed_policy_failure_not_child_crash(monkeypatch):
    from agent_runtime.public_dns import public_host_ips
    from agent_tools.web_gateway import WebGatewayError

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers("127.0.0.1"))
    with pytest.raises(WebGatewayError) as error:
        public_host_ips("example.com")
    assert error.value.reason == "private_network_blocked"


def test_synthetic_teredo_answer_replaces_entire_dns_set(monkeypatch):
    from agent_runtime import public_dns

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: answers("108.160.170.26", "2001::c760:3f35")
    )
    monkeypatch.setattr(public_dns, "_doh_addresses", lambda host: ("104.20.41.132",))
    assert public_dns.public_addresses("api.coingecko.com", 443) == answers("104.20.41.132")


def test_teredo_mixed_with_private_address_stays_blocked(monkeypatch):
    from agent_runtime import public_dns

    fallback = Mock()
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: answers("2001::c760:3f35", "10.0.0.1")
    )
    monkeypatch.setattr(public_dns, "_doh_addresses", fallback)
    with pytest.raises(OSError):
        public_dns.public_addresses("example.com", 443)
    fallback.assert_not_called()
