from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import socket
from threading import Event, Thread

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolResult
from agent_runtime.search_providers import SearXNGSearchProvider
from agent_tools.search_pipeline import SearchPipeline, SearchPipelineTool, SearchProviderRegistry


@contextmanager
def http_source(mode: str) -> Iterator[tuple[str, list[str]]]:
    requests: list[str] = []
    release = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            body = b'{"results": []}'
            status = 200
            content_type = "application/json"
            if mode == "hits":
                body = b'{"results": [{"url": "https://docs.example/evidence"}]}'
            elif mode == "shape":
                body = b"{}"
            elif mode == "invalid_hit":
                body = b'{"results": [{"url": "file:///not-a-public-source"}]}'
            elif mode == "mixed_invalid_hit":
                body = b'{"results": [{"url": "https://docs.example/evidence"}, {}]}'
            elif mode == "engine_failure":
                body = b'{"results": [], "unresponsive_engines": [["engine", "timeout"]]}'
            elif mode == "partial_engines":
                body = (
                    b'{"results": [{"url": "https://docs.example/evidence"}], '
                    b'"unresponsive_engines": [["engine", "timeout"]]}'
                )
            elif mode == "json":
                body = b"{broken"
            elif mode == "html":
                content_type = "text/html"
            elif mode == "oversized":
                body += b" " * 512
            elif mode in {"206", "401", "403", "503", "302"}:
                status = int(mode)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body) + (10 if mode == "incomplete" else 0)))
            if mode == "302":
                self.send_header("Location", "/must-not-follow")
            self.end_headers()
            try:
                if mode == "slow":
                    self.wfile.write(body[:1])
                    self.wfile.flush()
                    release.wait(0.2)
                    self.wfile.write(body[1:])
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The timed-out native client is expected to close its socket.
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/search", requests
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        assert not thread.is_alive()


def search(endpoint: str) -> ToolResult:
    registry = SearchProviderRegistry()
    registry.register(SearXNGSearchProvider(endpoint=endpoint), default=True)
    return SearchPipelineTool(SearchPipeline(registry)).handle(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="web.search",
            created_at=datetime.now(UTC),
            arguments={"query": "evidence"},
        )
    )


@pytest.fixture
def isolated_http(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the loopback egress preflight is replaced: urllib, HTTP parsing and sockets are real.
    monkeypatch.setattr("agent_runtime.search_providers._proxy_configuration", lambda *a, **k: {})
    monkeypatch.setattr("agent_runtime.search_providers.MAX_SEARCH_RESPONSE_BYTES", 256)
    monkeypatch.setattr(
        "agent_runtime.search_providers.DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS", 0.03, raising=False
    )


@pytest.mark.usefixtures("isolated_http")
@pytest.mark.parametrize(
    "mode,reason",
    [
        ("shape", "invalid_search_response"),
        ("invalid_hit", "invalid_search_response"),
        ("mixed_invalid_hit", "invalid_search_response"),
        ("engine_failure", "search_incomplete"),
        ("partial_engines", "search_incomplete"),
        ("206", "search_incomplete"),
        ("json", "invalid_search_response"),
        ("html", "unsupported_content_type"),
        ("oversized", "response_too_large"),
        ("incomplete", "response_incomplete"),
        ("slow", "gateway_unavailable"),
        ("401", "access_denied"),
        ("403", "access_denied"),
        ("503", "http_error"),
        ("302", "redirect_blocked"),
    ],
)
def test_native_http_failures_never_become_successful_empty(mode: str, reason: str) -> None:
    with http_source(mode) as (endpoint, requests):
        result = search(endpoint)
    assert result.status.value == "failed"
    assert result.metadata["reason"] == reason
    assert "result_count" not in result.metadata and "web_envelope" not in result.metadata
    assert not result.output and len(requests) == 1


@pytest.mark.usefixtures("isolated_http")
@pytest.mark.parametrize("mode,count", [("empty", 0), ("hits", 1)])
def test_native_http_real_empty_and_nonempty_remain_successful(mode: str, count: int) -> None:
    with http_source(mode) as (endpoint, requests):
        result = search(endpoint)
    assert result.status.value == "executed"
    assert result.metadata["result_count"] == count
    assert result.metadata["degraded"] is False
    assert result.metadata["untrusted_external_content"] is True
    assert result.metadata["web_envelope"]["untrusted_external_content"] is True
    assert len(requests) == 1


@pytest.mark.usefixtures("isolated_http")
def test_native_connection_refusal_is_not_empty() -> None:
    with socket() as reserved:
        reserved.bind(("127.0.0.1", 0))  # Reserved but not listening: real connect refusal.
        result = search(f"http://127.0.0.1:{reserved.getsockname()[1]}/search")
    assert result.status.value == "failed"
    assert result.metadata["reason"] == "gateway_unavailable"
    assert "result_count" not in result.metadata


def test_private_network_guard_still_blocks_before_native_http() -> None:
    result = search("http://127.0.0.1:1/search")
    assert result.status.value == "failed"
    assert result.metadata["reason"] == "private_network_blocked"


def test_unavailable_provider_is_never_called() -> None:
    def forbidden_fetch(_url: str) -> object:
        pytest.fail("an unavailable dependency must not be called")

    provider = SearXNGSearchProvider(
        endpoint="https://search.example/search", available=False, fetch_json=forbidden_fetch
    )
    registry = SearchProviderRegistry()
    registry.register(provider, default=True)
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.search",
        created_at=datetime.now(UTC),
        arguments={"query": "evidence"},
    )
    result = SearchPipelineTool(SearchPipeline(registry)).handle(call)
    assert result.status.value == "failed" and result.metadata["reason"] == "provider_unavailable"
