from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_runtime.crawl_gateway import Crawl4AIFetchProvider, CrawlGateway, is_crawl4ai_available
from agent_storage.web_resource import SQLiteWebResourceStore
from agent_tools.web_crawl import (
    FetchProviderError,
    FetchRequest,
    FetchResult,
    WebFetchV2Tool,
)
from agent_tools.web_projection import WebProjector


class OfflineFetchProvider:
    """Deterministic fetch double: returns canned markdown keyed by URL path."""

    def __init__(self, content_by_url: dict[str, str]) -> None:
        self.content_by_url = content_by_url

    @property
    def name(self) -> str:
        return "offline"

    @property
    def available(self) -> bool:
        return True

    def fetch(self, request: FetchRequest) -> FetchResult:
        markdown = self.content_by_url.get(request.url, "fallback content")
        return FetchResult(
            requested_url=request.url,
            final_url=request.url,
            clean_markdown=markdown,
            fetch_mode="http",
            complete=True,
            content_type="text/html",
            title="Offline Page",
            wire_bytes=len(markdown.encode("utf-8")),
            decoded_bytes=len(markdown.encode("utf-8")),
        )


def _public_resolver(_host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _gateway(tmp_path, *, content_by_url=None, resolver=None, max_clean_chars=2_000_000):
    store = SQLiteWebResourceStore(tmp_path / "web.db", tmp_path / "cache")
    provider = OfflineFetchProvider(content_by_url or {})
    if resolver is None:
        # Tests inject a public resolver so they don't depend on sandbox DNS
        # (which may map example.com to RFC2544 benchmarking ranges).
        resolver = _public_resolver
    return CrawlGateway(
        provider=provider,
        store=store,
        projector=WebProjector(),
        resolver=resolver,
        max_clean_chars=max_clean_chars,
    )


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


def test_gateway_fetch_persists_and_returns_resource_id(tmp_path) -> None:
    markdown = "# Revenue\n\n" + "quarterly revenue detail " * 200
    gateway = _gateway(tmp_path, content_by_url={"https://example.com/f": markdown})

    outcome = gateway.fetch(FetchRequest(url="https://example.com/f"), max_output_tokens=4_000)

    assert outcome.resource_id.startswith("web_")
    assert outcome.provider == "offline"
    assert outcome.final_url == "https://example.com/f"
    assert "revenue" in outcome.content.lower()
    # persisted and retrievable
    from agent_core.domain.web_resource import WebResourceId

    assert gateway.store.get(WebResourceId.parse(outcome.resource_id)) is not None


def test_gateway_dedups_identical_content(tmp_path) -> None:
    markdown = "identical body content about margin"
    gateway = _gateway(tmp_path, content_by_url={"https://example.com/a": markdown})

    first = gateway.fetch(FetchRequest(url="https://example.com/a"), max_output_tokens=2_000)
    second = gateway.fetch(FetchRequest(url="https://example.com/a"), max_output_tokens=2_000)

    assert first.resource_id == second.resource_id


def test_gateway_blocks_runtime_ssrf(tmp_path) -> None:
    gateway = _gateway(
        tmp_path,
        content_by_url={"https://evil.example/x": "data"},
        resolver=lambda _host: ("10.0.0.5",),
    )

    with pytest.raises(FetchProviderError, match="disallowed") as exc_info:
        gateway.fetch(FetchRequest(url="https://evil.example/x"), max_output_tokens=1_000)
    assert exc_info.value.reason == "ssrf_blocked"


def test_gateway_enforces_clean_budget(tmp_path) -> None:
    big = "word " * 50_000  # ~250k chars, well over a small cap
    gateway = _gateway(
        tmp_path, content_by_url={"https://example.com/big": big}, max_clean_chars=10_000
    )

    outcome = gateway.fetch(FetchRequest(url="https://example.com/big"), max_output_tokens=2_000)

    assert outcome.truncated is True
    from agent_core.domain.web_resource import WebResourceId

    record = gateway.store.get(WebResourceId.parse(outcome.resource_id))
    assert record is not None
    assert record.clean_chars == 10_000  # capped before persistence


def test_fetch_tool_returns_untrusted_result_and_resource_id(tmp_path) -> None:
    gateway = _gateway(tmp_path, content_by_url={"https://example.com/p": "# Title\n\nbody text"})
    tool = WebFetchV2Tool(gateway=gateway)
    call = _call("web.fetch", {"url": "https://example.com/p"})

    result = tool.handle(call)

    assert result.status.value == "executed"
    assert result.metadata["resource_id"].startswith("web_")
    assert result.metadata["untrusted_external_content"] is True
    assert "[UNTRUSTED EXTERNAL CONTENT]" in result.output


def test_fetch_tool_rejects_invalid_url(tmp_path) -> None:
    gateway = _gateway(tmp_path)
    tool = WebFetchV2Tool(gateway=gateway)
    call = _call("web.fetch", {"url": "ftp://example.com/x"})

    result = tool.handle(call)

    assert result.status.value == "failed"
    assert result.metadata["reason"] == "invalid_web_target"


def test_crawl4ai_provider_reports_availability_and_blocks_without_dep() -> None:
    provider = Crawl4AIFetchProvider()

    assert provider.available is is_crawl4ai_available()
    if not is_crawl4ai_available():
        with pytest.raises(FetchProviderError, match="crawl4ai is not installed"):
            provider.fetch(FetchRequest(url="https://example.com/x"))
