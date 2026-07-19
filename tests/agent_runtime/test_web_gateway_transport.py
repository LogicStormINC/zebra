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
    assert response.metadata == {
        "transport": "local_https",
        "redirects_followed": 0,
        "content_projection": "decoded_text",
        "output_byte_count": 10,
        "output_truncated": False,
    }


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


def test_trusted_local_web_gateway_uses_system_https_proxy_without_local_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = FakeOpener(FakeResponse(b"proxy-ok"))
    handlers: list[object] = []
    monkeypatch.setattr(
        "agent_runtime.web_gateway.urllib.request.getproxies",
        lambda: {"https": "http://127.0.0.1:7890"},
    )
    monkeypatch.setattr(
        "agent_runtime.web_gateway.socket.getaddrinfo",
        lambda *args, **kwargs: pytest.fail("proxy mode must not resolve fake IP locally"),
    )

    def capture_opener(*items: object) -> FakeOpener:
        handlers.extend(items)
        return opener

    monkeypatch.setattr(
        "agent_runtime.web_gateway.urllib.request.build_opener",
        capture_opener,
    )

    response = LocalWebGatewayTransport(use_system_proxy=True).execute(
        WebGatewayRequest(
            tool_call_id="call-proxy",
            target=parse_web_target("https://openai.com/news/"),
        )
    )

    assert response.text == "proxy-ok"
    assert handlers[0].proxies["https"] == "http://127.0.0.1:7890"  # type: ignore[attr-defined]


def test_local_web_gateway_projects_html_and_reports_bounded_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = FakeOpener(
        FakeResponse(
            b"<html><body><h1>Readable</h1><script>hidden()</script><p>Evidence</p></body></html>",
            "text/html; charset=utf-8",
        )
    )
    monkeypatch.setattr(
        "agent_runtime.web_gateway.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        "agent_runtime.web_gateway.urllib.request.build_opener",
        lambda *handlers: opener,
    )

    response = LocalWebGatewayTransport().execute(
        WebGatewayRequest(
            tool_call_id="call-html",
            target=parse_web_target("https://example.com/article"),
            max_output_bytes=64,
        )
    )

    assert response.text == "Readable\n\nEvidence"
    assert response.byte_count == 83
    assert response.metadata == {
        "transport": "local_https",
        "redirects_followed": 0,
        "content_projection": "html_to_text",
        "output_byte_count": 18,
        "output_truncated": False,
    }


def test_local_web_gateway_rejects_empty_html_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = FakeOpener(FakeResponse(b"<script>hidden()</script>", "text/html"))
    monkeypatch.setattr(
        "agent_runtime.web_gateway.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        "agent_runtime.web_gateway.urllib.request.build_opener",
        lambda *handlers: opener,
    )

    with pytest.raises(WebGatewayError, match="no readable text") as error:
        LocalWebGatewayTransport().execute(
            WebGatewayRequest(
                tool_call_id="call-empty",
                target=parse_web_target("https://example.com/empty"),
            )
        )

    assert error.value.reason == "content_projection_failed"
