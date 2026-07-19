import json
from email.message import Message

import pytest
from agent_core.domain.web import parse_web_target
from agent_runtime.web_search import LocalWebSearchTransport
from agent_tools.web_gateway import WebGatewayError
from agent_tools.web_search import WebSearchRequest


class FakeResponse:
    status = 200

    def __init__(self, payload: object, content_type: str = "application/json") -> None:
        self._body = json.dumps(payload).encode()
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(self._body))

    def __enter__(self):
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return None

    def read(self, size: int) -> bytes:
        return self._body[:size]


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[object, float]] = []

    def open(self, request, *, timeout):  # type: ignore[no-untyped-def]
        self.requests.append((request, timeout))
        return self.response


def test_searxng_adapter_executes_one_bounded_get_and_normalizes_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = FakeOpener(
        FakeResponse(
            {
                "results": [
                    {
                        "title": " First   result ",
                        "url": "https://docs.example.com/one#section",
                        "content": " Useful   evidence ",
                    },
                    {
                        "title": "duplicate",
                        "url": "https://docs.example.com/one",
                        "content": "ignored",
                    },
                    {"title": "unsafe", "url": "http://example.com", "content": "no"},
                ]
            }
        )
    )
    monkeypatch.setattr(
        "agent_runtime.web_gateway.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        "agent_runtime.web_search.urllib.request.build_opener",
        lambda *handlers: opener,
    )

    response = LocalWebSearchTransport().execute(_request())

    outbound, timeout = opener.requests[0]
    assert outbound.get_method() == "GET"
    assert outbound.data is None
    assert "Authorization" not in outbound.headers
    assert "q=zebra+agent" in outbound.full_url
    assert "format=json" in outbound.full_url
    assert "limit=2" in outbound.full_url
    assert timeout == 10.0
    assert [(item.title, item.url, item.snippet) for item in response.results] == [
        ("First result", "https://docs.example.com/one", "Useful evidence")
    ]
    assert response.provider == "searxng"
    assert response.metadata == {"transport": "local_https", "redirects_followed": 0}


def test_searxng_adapter_rejects_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = FakeOpener(FakeResponse({"results": []}, "text/html"))
    monkeypatch.setattr(
        "agent_runtime.web_gateway.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        "agent_runtime.web_search.urllib.request.build_opener",
        lambda *handlers: opener,
    )

    with pytest.raises(WebGatewayError) as error:
        LocalWebSearchTransport().execute(_request())

    assert error.value.reason == "unsupported_content_type"


def test_trusted_local_search_uses_system_https_proxy_without_local_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = FakeOpener(FakeResponse({"results": []}))
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
        "agent_runtime.web_search.urllib.request.build_opener",
        capture_opener,
    )

    response = LocalWebSearchTransport(use_system_proxy=True).execute(_request())

    assert response.results == ()
    assert handlers[0].proxies["https"] == "http://127.0.0.1:7890"  # type: ignore[attr-defined]


def _request() -> WebSearchRequest:
    return WebSearchRequest(
        tool_call_id="call-search",
        endpoint=parse_web_target("https://search.example.com/search"),
        query="zebra agent",
        limit=2,
    )
