from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_tools.search_pipeline import (
    MAX_SEARCH_LIMIT,
    SearchHit,
    SearchInputError,
    SearchPipeline,
    SearchPipelineTool,
    SearchProvider,
    SearchProviderRegistry,
    SearchQuery,
    web_search_v2_contract,
    apply_filters,
    expand_query,
    keyword_coverage_score,
    parse_search_query,
    reciprocal_rank_fusion,
    rerank_hits,
)


def _hit(url: str, title: str = "t", snippet: str = "") -> SearchHit:
    domain = url.split("//", 1)[-1].split("/", 1)[0]
    return SearchHit(title=title, url=url, snippet=snippet, domain=domain)


class StubProvider:
    def __init__(self, mapping: dict[str, tuple[SearchHit, ...]]) -> None:
        self.mapping = mapping
        self.queries: list[str] = []

    @property
    def name(self) -> str:
        return "stub"

    @property
    def available(self) -> bool:
        return True

    def search(self, query: SearchQuery, *, limit: int) -> tuple[SearchHit, ...]:
        self.queries.append(query.query)
        return self.mapping.get(query.query, ())[:limit]


def _registry(provider: SearchProvider) -> SearchProviderRegistry:
    registry = SearchProviderRegistry()
    registry.register(provider, default=True)
    return registry


def test_parse_rejects_unknown_and_invalid_arguments() -> None:
    with pytest.raises(SearchInputError):
        parse_search_query({"query": "x", "bogus": 1})
    with pytest.raises(SearchInputError):
        parse_search_query({"query": "x", "limit": 0})
    with pytest.raises(SearchInputError):
        parse_search_query({"query": "x", "time_range": "decade"})
    with pytest.raises(SearchInputError):
        parse_search_query({"query": "x", "min_score": 2.0})
    with pytest.raises(SearchInputError):
        parse_search_query({"query": "x", "include_domains": "example.com"})
    assert parse_search_query({"query": "revenue growth"}).query == "revenue growth"


def test_expand_query_drops_stopwords_for_a_variant() -> None:
    variants = expand_query(SearchQuery(query="what is the revenue growth"))

    assert variants[0] == "what is the revenue growth"
    assert "revenue growth" in variants


def test_reciprocal_rank_fusion_promotes_consensus_hits() -> None:
    a = (_hit("https://b.example/y"), _hit("https://a.example/x"), _hit("https://c.example/z"))
    b = (_hit("https://b.example/y"), _hit("https://a.example/x"), _hit("https://d.example/w"))

    fused = reciprocal_rank_fusion((a, b))

    assert fused[0].url == "https://b.example/y"
    assert fused[1].url == "https://a.example/x"
    urls = {hit.url for hit in fused}
    assert urls == {"https://a.example/x", "https://b.example/y", "https://c.example/z", "https://d.example/w"}


def test_keyword_coverage_and_rerank() -> None:
    assert keyword_coverage_score("revenue margin", "revenue and margin details") == 1.0
    assert keyword_coverage_score("revenue margin", "only revenue") == 0.5
    reranked = rerank_hits(
        (
            _hit("https://a.example/1", snippet="unrelated text"),
            _hit("https://b.example/2", snippet="revenue margin figures"),
        ),
        "revenue margin",
    )
    assert reranked[0].url == "https://b.example/2"


def test_apply_filters_resolves_subdomains() -> None:
    query = SearchQuery(
        query="x",
        include_domains=("example.com",),
        exclude_domains=("bad.example.com",),
    )
    hits = (
        _hit("https://example.com/a"),
        _hit("https://docs.example.com/b"),
        _hit("https://other.org/c"),
        _hit("https://bad.example.com/d"),
    )
    filtered = apply_filters(hits, query)
    assert {hit.url for hit in filtered} == {"https://example.com/a", "https://docs.example.com/b"}


def test_pipeline_runs_expansion_filters_and_caps(tmp_path) -> None:
    provider = StubProvider(
        {
            "revenue growth": (
                _hit("https://a.example/a", snippet="revenue growth up"),
                _hit("https://b.example/b", snippet="growth figures"),
                _hit("https://c.example/c", snippet="unrelated"),
            ),
        }
    )
    pipeline = SearchPipeline(registry=_registry(provider))
    query = SearchQuery(query="revenue growth", limit=2)

    result = pipeline.run(query)

    assert result.provider == "stub"
    assert len(result.hits) <= 2
    assert result.expanded_query_count >= 1
    # the most query-relevant hit ranks first
    assert result.hits[0].url == "https://a.example/a"


def test_pipeline_auto_fetch_reranks_by_content() -> None:
    provider = StubProvider(
        {
            "revenue": (
                _hit("https://a.example/a", snippet="nothing useful"),
                _hit("https://b.example/b", snippet="revenue mentioned"),
            ),
        }
    )

    def fetcher(url: str) -> str | None:
        if url.endswith("/a"):
            return "full text with revenue and margin discussion"
        return "generic page content without keywords"

    pipeline = SearchPipeline(registry=_registry(provider), fetcher=fetcher)
    result = pipeline.run(SearchQuery(query="revenue", limit=5, auto_fetch=2))

    assert result.fetched_count == 2
    # content match lifts the previously-irrelevant hit to the top
    assert result.hits[0].url == "https://a.example/a"
    assert result.hits[0].fetch_status == "fetched"


def test_pipeline_tool_emits_envelope_and_untrusted_flag() -> None:
    provider = StubProvider({"revenue": (_hit("https://a.example/a", snippet="revenue"),)})
    tool = SearchPipelineTool(pipeline=SearchPipeline(registry=_registry(provider)))
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.search",
        arguments={"query": "revenue", "limit": 5},
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    result = tool.handle(call)

    assert result.status.value == "executed"
    assert result.metadata["untrusted_external_content"] is True
    assert result.metadata["provider"] == "stub"
    assert result.metadata["web_envelope"]["untrusted_external_content"] is True
    assert (
        result.metadata["web_envelope"]["capability_version"]
        == web_search_v2_contract.capability_version
    )
    assert "[UNTRUSTED EXTERNAL SEARCH RESULTS]" in result.output


def test_pipeline_tool_rejects_invalid_input() -> None:
    provider = StubProvider({"revenue": (_hit("https://a.example/a"),)})
    tool = SearchPipelineTool(pipeline=SearchPipeline(registry=_registry(provider)))
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.search",
        arguments={"query": "revenue", "limit": MAX_SEARCH_LIMIT + 1},
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    result = tool.handle(call)

    assert result.status.value == "failed"
    assert result.metadata["reason"] == "invalid_search_input"
