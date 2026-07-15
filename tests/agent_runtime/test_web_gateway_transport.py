from email.message import Message

import pytest
from agent_core.domain.web import parse_web_target
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_tools.web_gateway import WebGatewayError, WebGatewayRequest


class FakeResponse:
    status = 200

    def __init__(self, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def __enter__(self):
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return None

    def read(self, size: int) -> bytes:
        return self._body[:size]


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[object] = []

    def open(self, request, *, timeout):  # type: ignore[no-untyped-def]
        self.requests.append((request, timeout))
        return self.response


def test_local_web_gateway_executes_one_bounded_get_without_caller_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = FakeOpener(FakeResponse(b"gateway-ok"))
    monkeypatch.setattr(
        "agent_runtime.web_gateway.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        "agent_runtime.web_gateway.urllib.request.build_opener",
        lambda *handlers: opener,
    )
    request = WebGatewayRequest(
        tool_call_id="call-1",
        target=parse_web_target("https://example.com/info"),
        max_bytes=32,
    )

    response = LocalWebGatewayTransport().execute(request)

    outbound, timeout = opener.requests[0]
    assert outbound.get_method() == "GET"
    assert outbound.data is None
    assert "Authorization" not in outbound.headers
    assert timeout == 10.0
    assert response.text == "gateway-ok"
    assert response.metadata == {"transport": "local_https", "redirects_followed": 0}


def test_local_web_gateway_blocks_private_dns_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_runtime.web_gateway.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    request = WebGatewayRequest(
        tool_call_id="call-1",
        target=parse_web_target("https://example.com/info"),
    )

    with pytest.raises(WebGatewayError, match="non-public") as error:
        LocalWebGatewayTransport().execute(request)

    assert error.value.reason == "private_network_blocked"
