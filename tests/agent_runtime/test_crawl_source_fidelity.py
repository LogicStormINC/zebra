import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace, TracebackType

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_core.domain.web import TruncationScope
from agent_core.domain.web_resource import WebResourceId
from agent_runtime.crawl_gateway import Crawl4AIFetchProvider, CrawlGateway
from agent_storage.web_resource import SQLiteWebResourceStore, WebResourceStoreAdapter
from agent_tools.web_crawl import (
    CrawlGatewayPort,
    FetchOutcome,
    FetchProviderError,
    FetchRequest,
    FetchResult,
    WebCrawlTool,
    WebExtractTool,
    WebFetchV2Tool,
)
from agent_tools.web_projection import WebFindTool, WebProjector, WebReadTool

URL = "https://source.example/evidence"
ENTRYPOINTS = ("web.fetch", "web.crawl", "web.extract")


class SourceProvider:
    name = "isolated-source"
    available = True

    def __init__(self, clean: str, *, complete: bool, failed: bool = False) -> None:
        self.clean = clean
        self.complete = complete
        self.failed = failed

    def fetch(self, request: FetchRequest) -> FetchResult:
        if self.failed:
            raise FetchProviderError("source refused", reason="source_refused")
        return FetchResult(
            requested_url=request.url,
            final_url=request.url,
            clean_markdown=self.clean,
            fetch_mode="http",
            complete=self.complete,
        )


def gateway(tmp_path: Path, provider: SourceProvider, *, cap: int = 10000) -> CrawlGateway:
    return CrawlGateway(
        provider=provider,
        store=SQLiteWebResourceStore(tmp_path / "isolated.sqlite", tmp_path / "cache"),
        projector=WebProjector(),
        max_clean_chars=cap,
        resolver=lambda _hostname: ("93.184.216.34",),
    )


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        created_at=datetime.now(UTC),
        arguments={"url": URL, **arguments},
    )


def tool(name: str, source: CrawlGatewayPort) -> WebFetchV2Tool | WebCrawlTool | WebExtractTool:
    tools: dict[str, type[WebFetchV2Tool] | type[WebCrawlTool] | type[WebExtractTool]] = {
        "web.fetch": WebFetchV2Tool,
        "web.crawl": WebCrawlTool,
        "web.extract": WebExtractTool,
    }
    return tools[name](gateway=source)


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize("source_state", ["complete", "partial", "clean_cap"])
@pytest.mark.parametrize("projection_partial", [False, True])
def test_all_entrypoints_keep_source_and_projection_limits_independent(
    tmp_path: Path, name: str, source_state: str, projection_partial: bool
) -> None:
    source = gateway(
        tmp_path,
        SourceProvider("evidence " * 200, complete=source_state != "partial"),
        cap=40 if source_state == "clean_cap" else 10000,
    )
    result = tool(name, source).handle(
        call(name, max_output_tokens=1 if projection_partial else 8000)
    )
    source_partial = source_state != "complete"
    assert result.status.value == "executed"
    for metadata in (result.metadata, result.metadata["web_envelope"]):
        assert metadata["source_truncated"] is source_partial
        assert metadata["projection_truncated"] is projection_partial
        assert metadata["truncated"] is (source_partial or projection_partial)
        assert metadata["degraded"] is source_partial
        assert metadata["truncation_scope"] == (
            "projection" if projection_partial else "source" if source_partial else "none"
        )
        assert metadata["untrusted_external_content"] is True
    resource_id = WebResourceId.parse(result.metadata["resource_id"])
    adapter = WebResourceStoreAdapter(source.store)
    for reader in (WebReadTool(adapter, WebProjector()), WebFindTool(adapter, WebProjector())):
        resumed = reader.handle(
            call(reader.contract.name, resource_id=resource_id.value, query="evidence")
        )
        assert resumed.status.value == "executed"
        assert resumed.metadata["source_truncated"] is source_partial
        assert resumed.metadata["projection_truncated"] is False
    assert str(tmp_path) not in str(result.metadata)


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize(
    "clean,complete,cap", [("", False, 10000), (" " * 41 + "evidence", True, 40)]
)
def test_empty_partial_is_typed_failure_before_cache_admission(
    tmp_path: Path, name: str, clean: str, complete: bool, cap: int
) -> None:
    source = gateway(tmp_path, SourceProvider(clean, complete=complete), cap=cap)
    result = tool(name, source).handle(call(name))
    assert result.status.value == "failed"
    assert result.metadata["reason"] == "source_incomplete"
    assert not result.output and "web_envelope" not in result.metadata
    with source.store._database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM web_resource").fetchone()[0] == 0


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_genuine_complete_empty_remains_distinct_from_failure(tmp_path: Path, name: str) -> None:
    source = gateway(tmp_path, SourceProvider("", complete=True))
    result = tool(name, source).handle(call(name))
    assert result.status.value == "executed"
    for metadata in (result.metadata, result.metadata["web_envelope"]):
        assert metadata["source_truncated"] is False
        assert metadata["projection_truncated"] is False
        assert metadata["truncated"] is False and metadata["degraded"] is False
        assert metadata["truncation_scope"] == "none"


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_provider_failure_is_not_successful_empty(tmp_path: Path, name: str) -> None:
    source = gateway(tmp_path, SourceProvider("", complete=True, failed=True))
    result = tool(name, source).handle(call(name))
    assert result.status.value == "failed" and result.metadata["reason"] == "source_refused"
    assert not result.output and "resource_id" not in result.metadata


def test_legacy_outcome_dimensions_remain_explicitly_unknown() -> None:
    class LegacyGateway:
        def fetch(self, request: FetchRequest, *, max_output_tokens: int) -> FetchOutcome:
            return FetchOutcome(
                WebResourceId.new().value,
                None,
                request.url,
                "legacy evidence",
                True,
                TruncationScope.PROJECTION,
                None,
                "legacy",
            )

    result = WebFetchV2Tool(LegacyGateway()).handle(call("web.fetch"))
    assert result.status.value == "executed"
    assert result.metadata["web_envelope"]["source_truncated"] is None
    assert result.metadata["web_envelope"]["projection_truncated"] is None


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_extra_metadata_cannot_downgrade_canonical_source_flags(tmp_path: Path, name: str) -> None:
    source = gateway(tmp_path, SourceProvider("evidence", complete=False))

    class ExtraMetadataGateway:
        def fetch(self, request: FetchRequest, *, max_output_tokens: int) -> FetchOutcome:
            return replace(
                source.fetch(request, max_output_tokens=max_output_tokens),
                metadata={
                    "source_truncated": False,
                    "degraded": False,
                    "untrusted_external_content": False,
                },
            )

    result = tool(name, ExtraMetadataGateway()).handle(call(name))
    assert result.metadata["source_truncated"] is True
    assert result.metadata["degraded"] is True
    assert result.metadata["untrusted_external_content"] is True


@pytest.mark.parametrize("name", ENTRYPOINTS)
@pytest.mark.parametrize("change", ["partial_to_complete", "complete_to_partial", "foreign_url"])
def test_hash_dedup_cannot_adopt_incompatible_source_headers(
    tmp_path: Path, name: str, change: str
) -> None:
    provider = SourceProvider("evidence", complete=change != "partial_to_complete")
    source = gateway(tmp_path, provider)
    first = tool(name, source).handle(call(name))
    assert first.status.value == "executed"
    resource_id = WebResourceId.parse(first.metadata["resource_id"])
    original = source.store.get(resource_id)
    if change != "foreign_url":
        provider.complete = not provider.complete
    second = tool(name, source).handle(
        call(name, url="https://other.example/evidence" if change == "foreign_url" else URL)
    )
    assert second.status.value == "failed" and not second.output
    assert second.metadata["reason"] == "resource_source_mismatch"
    assert source.store.get(resource_id) == original


@pytest.mark.parametrize("success,status", [(False, 503), (None, 200), (True, 503), (True, None)])
def test_browser_provider_cannot_fabricate_complete_empty_from_failed_or_unknown_outcome(
    success: bool | None, status: int | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Crawler:
        def __init__(self, *, headless: bool) -> None:
            pass

        async def __aenter__(self) -> "Crawler":
            return self

        async def __aexit__(
            self,
            kind: type[BaseException] | None,
            error: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            pass

        async def arun(self, *, url: str) -> SimpleNamespace:
            return SimpleNamespace(success=success, status_code=status, markdown="", metadata={})

    backend = ModuleType("crawl4ai")
    monkeypatch.setattr(backend, "AsyncWebCrawler", Crawler, raising=False)
    monkeypatch.setitem(sys.modules, "crawl4ai", backend)
    with pytest.raises(FetchProviderError) as caught:
        Crawl4AIFetchProvider().fetch(FetchRequest(URL))
    assert caught.value.reason == "fetch_provider_failed"
