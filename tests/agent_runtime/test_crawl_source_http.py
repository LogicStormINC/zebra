import json
import socket
import sqlite3
import ssl
import urllib.request
from asyncio import CancelledError
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from http.client import HTTPConnection, HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from time import monotonic

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_core.domain.web import parse_web_target
from agent_runtime.crawl_gateway import CrawlGateway
from agent_runtime.fetch_providers import LocalHttpFetchProvider
from agent_runtime.search_providers import SearXNGSearchProvider
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_runtime.web_search import LocalWebSearchTransport
from agent_runtime.web_tools import register_native_web_tools
from agent_storage.web_resource import SQLiteWebResourceStore, WebResourceStoreAdapter
from agent_tools import ToolRegistry
from agent_tools.search_pipeline import SearchPipeline, SearchPipelineTool, SearchProviderRegistry
from agent_tools.web_crawl import WebCrawlTool, WebExtractTool, WebFetchV2Tool
from agent_tools.web_gateway import WebGatewayError, WebGatewayRequest
from agent_tools.web_projection import WebFindTool, WebProjector, WebReadTool
from agent_tools.web_search import WebSearchTool
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

URL = "https://source.example/article"
ENTRYPOINTS = ("web.fetch", "web.crawl", "web.extract")


@contextmanager
def native_tls_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    *,
    trusted: bool = True,
    certificate_host: str = "source.example",
    on_listen: Callable[[int], None] | None = None,
) -> Iterator[tuple[list[str], Event, Event, Event, list[float]]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, certificate_host)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(certificate_host)]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "source-ca.pem", tmp_path / "source-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    requests: list[str] = []
    entered, peer_closed, release = Event(), Event(), Event()
    writes: list[float] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            body, content_type = b"evidence " * 20, "text/plain"
            if self.path.startswith("/search"):
                body, content_type = b'{"results": []}', "application/json"
                if mode == "engine_failure":
                    body = b'{"results": [], "unresponsive_engines": [["engine", "timeout"]]}'
            elif mode == "empty_html":
                body, content_type = b"<script>hidden()</script>", "text/html"
            self.send_response(206 if mode == "206" else 200)
            self.send_header("Content-Type", content_type)
            self.send_header(
                "Content-Length",
                str(4096 if mode == "drip" else len(body) + (mode == "incomplete")),
            )
            self.end_headers()
            entered.set()
            try:
                if mode == "drip":
                    while not release.wait(0.01):
                        self.wfile.write(b"e")
                        self.wfile.flush()
                        writes.append(monotonic())
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                peer_closed.set()
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    if on_listen is not None:
        on_listen(server.server_port)
    original_connect = socket.create_connection

    def route(
        address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
        *,
        all_errors: bool = False,
    ) -> socket.socket:
        assert address == ("source.example", 443)
        return original_connect(
            ("127.0.0.1", server.server_port), timeout, source_address, all_errors=all_errors
        )

    def isolated_proxy(hostname: str, *, use_system_proxy: bool) -> dict[str, str]:
        assert hostname == "source.example"
        return {}

    # Only approved-origin routing/preflight and a scratch CA change. Native TLS verifies SAN/CA.
    with monkeypatch.context() as isolation:
        if trusted:
            isolation.setenv("SSL_CERT_FILE", str(cert_path))
        else:
            isolation.delenv("SSL_CERT_FILE", raising=False)
        isolation.setattr(socket, "create_connection", route)
        isolation.setattr("agent_runtime.web_gateway._proxy_configuration", isolated_proxy)
        isolation.setattr("agent_runtime.search_providers._proxy_configuration", isolated_proxy)
        isolation.setattr("agent_runtime.web_search._proxy_configuration", isolated_proxy)
        try:
            yield requests, entered, peer_closed, release, writes
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
            assert not thread.is_alive()


@contextmanager
def native_http_source(mode: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    requests: list[str] = []
    release = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            body = b"evidence " * 20
            status = 200
            content_type = "text/plain"
            if self.path.startswith("/search"):
                body = json.dumps({"results": [{"url": URL, "title": "Evidence"}]}).encode()
                content_type = "application/json"
            elif mode == "upstream_cap":
                body = b"evidence " * 8000
            elif mode == "empty":
                body = b""
            elif mode == "empty_html":
                body = b"<script>hidden()</script>"
                content_type = "text/html"
            elif mode == "partial_content":
                status = 206
            elif mode in {"401", "403", "503", "302"}:
                status = int(mode)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if mode == "invalid_chunk" and not self.path.startswith("/search"):
                self.send_header("Transfer-Encoding", "chunked")
                body = b"A\r\nshort\r\n"
            else:
                self.send_header(
                    "Content-Length",
                    str(
                        len(body) + (17 if mode == "incomplete" and self.path == "/article" else 0)
                    ),
                )
            if status == 302:
                self.send_header("Location", "https://source.example/must-not-follow")
            self.end_headers()
            try:
                if mode == "slow":
                    self.wfile.write(body[:1])
                    self.wfile.flush()
                    release.wait(0.5)
                    self.wfile.write(body[1:])
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()

    class RoutedConnection(HTTPConnection):
        def __init__(
            self,
            host: str,
            *,
            port: int | None = None,
            timeout: float = 10,
            source_address: tuple[str, int] | None = None,
            blocksize: int = 8192,
        ) -> None:
            super().__init__(
                "127.0.0.1",
                server.server_port,
                timeout=timeout,
                source_address=source_address,
                blocksize=blocksize,
            )

    class RoutedHttpsHandler(urllib.request.HTTPSHandler):
        def https_open(self, request: urllib.request.Request) -> HTTPResponse:
            return self.do_open(RoutedConnection, request)

    original_opener = urllib.request.build_opener

    def isolated_opener(
        *handlers: urllib.request.BaseHandler | Callable[[], urllib.request.BaseHandler],
    ) -> urllib.request.OpenerDirector:
        return original_opener(*handlers, RoutedHttpsHandler())

    def isolated_proxy(hostname: str, *, use_system_proxy: bool) -> dict[str, str]:
        assert hostname == "source.example"
        return {}

    # Only endpoint routing/preflight change. urllib, sockets, response parsing and reads are real.
    # This proves native HTTP source semantics, not TLS or production egress acceptance.
    with monkeypatch.context() as isolation:
        isolation.setattr("urllib.request.build_opener", isolated_opener)
        isolation.setattr("agent_runtime.web_gateway._proxy_configuration", isolated_proxy)
        isolation.setattr("agent_runtime.search_providers._proxy_configuration", isolated_proxy)
        isolation.setattr(
            "agent_runtime.web_tools.CrawlGateway",
            partial(CrawlGateway, resolver=lambda _host: ("93.184.216.34",)),
        )
        try:
            yield requests
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
            assert not thread.is_alive()


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        created_at=datetime.now(UTC),
        arguments={**({"url": URL} if name in ENTRYPOINTS else {}), **arguments},
    )


def gateway(tmp_path: Path, *, cap: int = 100000, max_bytes: int = 2097152) -> CrawlGateway:
    return CrawlGateway(
        LocalHttpFetchProvider(max_bytes=max_bytes),
        SQLiteWebResourceStore(tmp_path / "isolated.sqlite", tmp_path / "cache"),
        WebProjector(),
        max_clean_chars=cap,
        resolver=lambda _host: ("93.184.216.34",),
    )


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize(
    "mode", ["normal", "upstream_cap", "clean_cap", "empty", "partial_content"]
)
def test_native_http_caps_are_source_partial_not_projection_or_failure(
    tmp_path: Path, name: str, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = gateway(tmp_path, cap=40 if mode == "clean_cap" else 100000)
    tools: dict[str, type[WebFetchV2Tool] | type[WebCrawlTool] | type[WebExtractTool]] = {
        "web.fetch": WebFetchV2Tool,
        "web.crawl": WebCrawlTool,
        "web.extract": WebExtractTool,
    }
    native_tool = tools[name](source)
    with native_http_source(mode, monkeypatch) as requests:
        result = native_tool.handle(call(name, max_output_tokens=100000))
    assert requests == ["/article"] and result.status.value == "executed"
    partial_source = mode in {"upstream_cap", "clean_cap", "partial_content"}
    for metadata in (result.metadata, result.metadata["web_envelope"]):
        assert metadata["source_truncated"] is partial_source
        assert metadata["projection_truncated"] is False
        assert metadata["truncated"] is partial_source and metadata["degraded"] is partial_source
        assert metadata["truncation_scope"] == ("source" if partial_source else "none")
        assert metadata["untrusted_external_content"] is True
    adapter = WebResourceStoreAdapter(source.store)
    for reader in (WebReadTool(adapter, WebProjector()), WebFindTool(adapter, WebProjector())):
        resumed = reader.handle(
            call(
                reader.contract.name,
                resource_id=result.metadata["resource_id"],
                query="evidence",
                max_output_tokens=100000,
            )
        )
        assert resumed.metadata["source_truncated"] is partial_source
        assert resumed.metadata["projection_truncated"] is False


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize(
    "mode,reason",
    [
        ("incomplete", "response_incomplete"),
        ("invalid_chunk", "response_incomplete"),
        ("401", "http_error"),
        ("403", "http_error"),
        ("503", "http_error"),
        ("302", "redirect_blocked"),
        ("empty_html", "content_projection_failed"),
        ("oversized", "response_too_large"),
    ],
)
def test_native_http_faults_are_typed_failed_for_every_entrypoint(
    tmp_path: Path, name: str, mode: str, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = gateway(tmp_path, max_bytes=32 if mode == "oversized" else 2097152)
    tools: dict[str, type[WebFetchV2Tool] | type[WebCrawlTool] | type[WebExtractTool]] = {
        "web.fetch": WebFetchV2Tool,
        "web.crawl": WebCrawlTool,
        "web.extract": WebExtractTool,
    }
    native_tool = tools[name](source)
    with native_http_source(mode, monkeypatch) as requests:
        result = native_tool.handle(call(name))
    assert requests == ["/article"]
    assert result.status.value == "failed" and result.metadata["reason"] == reason
    assert not result.output and "resource_id" not in result.metadata
    assert "web_envelope" not in result.metadata
    with source.store._database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM web_resource").fetchone()[0] == 0


@pytest.mark.parametrize(
    "mode,fetch_status,degraded",
    [
        ("normal", "fetched", False),
        ("upstream_cap", "partial", True),
        ("partial_content", "partial", True),
        ("503", "failed", True),
        ("403", "failed", True),
        ("302", "failed", True),
        ("incomplete", "failed", True),
        ("invalid_chunk", "failed", True),
        ("empty_html", "failed", True),
    ],
)
@pytest.mark.parametrize("trusted_local", [False, True])
def test_actual_registration_preserves_auto_fetch_source_outcome(
    tmp_path: Path,
    mode: str,
    fetch_status: str,
    degraded: bool,
    trusted_local: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ToolRegistry()
    # An unavailable optional browser uses the same guarded HTTP provider, never a fake success.
    monkeypatch.setattr("agent_runtime.web_tools.is_crawl4ai_available", lambda: False)
    with native_http_source(mode, monkeypatch) as requests:
        register_native_web_tools(
            registry,
            enabled_names=frozenset({"web.search"}),
            workspace_root=tmp_path,
            search_endpoint=parse_web_target("https://source.example/search"),
            trusted_local=trusted_local,
        )
        result = registry.get("web.search").handler(
            call("web.search", query="evidence", auto_fetch=1)
        )
    assert len(requests) == 2 and requests[0].startswith("/search?")
    assert requests[1] == "/article"
    assert result.status.value == "executed" and result.metadata["result_count"] == 1
    assert result.metadata["degraded"] is degraded
    envelope = result.metadata["web_envelope"]
    assert envelope["degraded"] is degraded
    assert envelope["extra"]["hits"][0]["fetch_status"] == fetch_status
    assert result.metadata["fetched_count"] == (1 if fetch_status == "fetched" else 0)


@pytest.mark.parametrize("name", (*ENTRYPOINTS, "web.search"))
@pytest.mark.parametrize("error_type", [CancelledError, SystemExit, KeyboardInterrupt])
def test_native_reader_cancellation_is_primary_closes_response_and_never_falls_back(
    tmp_path: Path, name: str, error_type: type[BaseException], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ToolRegistry()
    error = error_type("source stopped")
    responses: list[HTTPResponse] = []
    original_read = HTTPResponse.read

    def canceled_read(response: HTTPResponse, amt: int | None = None) -> bytes:
        if response.headers.get_content_type() == "text/plain":
            assert original_read(response, 1) == b"e"  # A real socket read precedes the signal.
            responses.append(response)
            raise error
        return original_read(response, amt)

    monkeypatch.setattr(HTTPResponse, "read", canceled_read)
    with native_http_source("normal", monkeypatch) as requests:
        register_native_web_tools(
            registry,
            enabled_names=frozenset({name}),
            workspace_root=tmp_path,
            search_endpoint=parse_web_target("https://source.example/search"),
            trusted_local=False,
        )
        arguments = {"query": "evidence", "auto_fetch": 1} if name == "web.search" else {}
        with pytest.raises(error_type) as caught:
            registry.get(name).handler(call(name, **arguments))
    assert caught.value is error
    assert len(responses) == 1 and responses[0].isclosed()
    assert len(requests) == (2 if name == "web.search" else 1)
    assert requests[-1] == "/article"
    with sqlite3.connect(tmp_path / ".zebra-agent" / "web_resources.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM web_resource").fetchone()[0] == 0


def test_native_stalled_body_times_out_and_closes_response(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[HTTPResponse] = []
    original_read = HTTPResponse.read

    def observed_read(response: HTTPResponse, amt: int | None = None) -> bytes:
        responses.append(response)
        return original_read(response, amt)

    monkeypatch.setattr(HTTPResponse, "read", observed_read)
    with native_http_source("slow", monkeypatch) as requests:
        started = monotonic()
        with pytest.raises(WebGatewayError) as caught:
            LocalWebGatewayTransport().execute(
                WebGatewayRequest("bounded-body", parse_web_target(URL), timeout_seconds=0.03)
            )
        assert monotonic() - started < 0.5  # The response body has not been released yet.
        assert caught.value.reason == "gateway_unavailable"
        assert len(responses) == 1 and responses[0].isclosed()
    assert requests == ["/article"]


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize(
    "mode,reason",
    [
        ("normal", None),
        ("206", None),
        ("incomplete", "response_incomplete"),
        ("empty_html", "content_projection_failed"),
    ],
)
def test_real_tls_preserves_source_status_and_readability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, mode: str, reason: str | None
) -> None:
    source = gateway(tmp_path)
    tools: dict[str, type[WebFetchV2Tool] | type[WebCrawlTool] | type[WebExtractTool]] = {
        "web.fetch": WebFetchV2Tool,
        "web.crawl": WebCrawlTool,
        "web.extract": WebExtractTool,
    }
    with native_tls_source(tmp_path, monkeypatch, mode) as (requests, entered, _, _, _):
        result = tools[name](source).handle(call(name))
        assert entered.is_set() and requests == ["/article"]
    if reason is not None:
        assert result.status.value == "failed" and result.metadata["reason"] == reason
        assert not result.output and "web_envelope" not in result.metadata
        with source.store._database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM web_resource").fetchone()[0] == 0
    else:
        assert result.status.value == "executed"
        assert result.metadata["source_truncated"] is (mode == "206")
        assert result.metadata["projection_truncated"] is False
        assert result.metadata["degraded"] is (mode == "206")


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize(
    "trusted,certificate_host", [(False, "source.example"), (True, "foreign.example")]
)
def test_real_tls_ca_and_hostname_fail_closed_before_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, trusted: bool, certificate_host: str
) -> None:
    source = gateway(tmp_path)
    tools: dict[str, type[WebFetchV2Tool] | type[WebCrawlTool] | type[WebExtractTool]] = {
        "web.fetch": WebFetchV2Tool,
        "web.crawl": WebCrawlTool,
        "web.extract": WebExtractTool,
    }
    with native_tls_source(
        tmp_path, monkeypatch, "normal", trusted=trusted, certificate_host=certificate_host
    ) as (requests, entered, _, _, _):
        result = tools[name](source).handle(call(name))
        assert not entered.is_set() and not requests
    assert result.status.value == "failed" and result.metadata["reason"] == "gateway_unavailable"
    assert not result.output and "resource_id" not in result.metadata


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize("error_type", [CancelledError, SystemExit, KeyboardInterrupt])
def test_real_tls_reader_signal_closes_actual_peer_not_just_python_response(
    tmp_path: Path, name: str, error_type: type[BaseException], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = gateway(tmp_path)
    tools: dict[str, type[WebFetchV2Tool] | type[WebCrawlTool] | type[WebExtractTool]] = {
        "web.fetch": WebFetchV2Tool,
        "web.crawl": WebCrawlTool,
        "web.extract": WebExtractTool,
    }
    signal = error_type("source stopped")
    original_read = HTTPResponse.read

    def stopped_read(response: HTTPResponse, amt: int | None = None) -> bytes:
        assert original_read(response, 1) == b"e"
        raise signal

    monkeypatch.setattr(HTTPResponse, "read", stopped_read)
    with native_tls_source(tmp_path, monkeypatch, "drip") as (requests, entered, closed, _, writes):
        with pytest.raises(error_type) as caught:
            tools[name](source).handle(call(name))
        assert caught.value is signal
        assert entered.is_set() and writes and requests == ["/article"]
        assert closed.wait(0.5)  # Server SSL writes fail while its own release remains unset.
    with source.store._database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM web_resource").fetchone()[0] == 0


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "mode,reason",
    [
        ("normal", None),
        ("206", "search_incomplete"),
        ("incomplete", "response_incomplete"),
        ("engine_failure", "search_incomplete"),
    ],
)
def test_real_tls_legacy_and_current_search_share_failure_not_empty_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool, mode: str, reason: str | None
) -> None:
    target = parse_web_target("https://source.example/search")
    tool: WebSearchTool | SearchPipelineTool
    if legacy:
        tool = WebSearchTool(target, LocalWebSearchTransport())
    else:
        registry = SearchProviderRegistry()
        registry.register(SearXNGSearchProvider(endpoint=target.url), default=True)
        tool = SearchPipelineTool(SearchPipeline(registry))
    with native_tls_source(tmp_path, monkeypatch, mode) as (requests, entered, _, _, _):
        result = tool.handle(call("web.search", query="evidence"))
        assert entered.is_set() and len(requests) == 1
    if reason is not None:
        assert result.status.value == "failed" and result.metadata["reason"] == reason
        assert not result.output and "result_count" not in result.metadata
    else:
        assert result.status.value == "executed" and result.metadata["result_count"] == 0
        assert result.metadata["untrusted_external_content"] is True
