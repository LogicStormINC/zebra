from __future__ import annotations

from agent_runtime.search_providers import SearXNGSearchProvider, _searxng_url
from agent_tools.search_pipeline import SearchHit, SearchQuery


def _fetch_returning(results: list[dict]) -> object:
    calls: list[str] = []

    def _fetch(url: str) -> dict:
        calls.append(url)
        return {"results": results}

    _fetch.calls = calls  # type: ignore[attr-defined]
    return _fetch


def test_searxng_url_passes_query_limit_and_time_range() -> None:
    url = _searxng_url(
        "https://searxng.example/search",
        query=SearchQuery(query="revenue growth", time_range="week"),
        limit=12,
    )

    assert "q=revenue+growth" in url
    assert "format=json" in url
    assert "limit=12" in url
    assert "time_range=week" in url


def test_searxng_provider_maps_normalizes_and_dedups() -> None:
    fetch = _fetch_returning(
        [
            {"title": "Revenue", "url": "https://docs.example.com/a#frag", "content": " growth "},
            {"title": "Revenue", "url": "https://docs.example.com/a", "content": "dup"},
            {"url": "https://docs.example.com/b", "content": "second"},
        ]
    )
    provider = SearXNGSearchProvider(endpoint="https://searxng.example/search", fetch_json=fetch)  # type: ignore[arg-type]

    hits = provider.search(SearchQuery(query="revenue", limit=5), limit=5)

    urls = [hit.url for hit in hits]
    assert urls == ["https://docs.example.com/a", "https://docs.example.com/b"]
    assert all(isinstance(hit, SearchHit) for hit in hits)
    assert hits[0].domain == "docs.example.com"
    assert hits[0].snippet == "growth"  # whitespace collapsed


def test_searxng_provider_caps_at_limit() -> None:
    fetch = _fetch_returning([{"url": f"https://x.example/{i}"} for i in range(10)])
    provider = SearXNGSearchProvider(endpoint="https://searxng.example/search", fetch_json=fetch)  # type: ignore[arg-type]

    hits = provider.search(SearchQuery(query="x", limit=3), limit=3)

    assert len(hits) == 3
