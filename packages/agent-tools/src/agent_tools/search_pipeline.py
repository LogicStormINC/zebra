"""Rebuilt web search pipeline (WEB-PIPE-SEARCH-01 + WEB-PIPE-SEARCH-Q-01).

Replaces the legacy single-backend SearXNG adapter with: a richer, versioned
``web.search`` contract (capability_version 2), a swappable ``SearchProvider``
registry (local SearXNG default, hosted opt-in later via Credential Broker),
and quality levers that stay local-first and credential-free — multi-query
expansion + reciprocal rank fusion, Zebra-side keyword rerank, and an optional
search->fetch->rerank loop (the same change that fixes search/fetch not being
connected). Fully offline-testable via injectable providers and fetchers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC
from typing import Protocol

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.web import TruncationScope, WebTargetError, parse_web_target

from agent_tools.contracts import ToolContract
from agent_tools.web_envelope import WEB_ENVELOPE_CAPABILITY_VERSION, WebResultEnvelope

MAX_SEARCH_QUERY_CHARS = 500
DEFAULT_SEARCH_LIMIT = 8
MAX_SEARCH_LIMIT = 20
MAX_DOMAIN_FILTERS = 20
TIME_RANGES = frozenset({"day", "week", "month", "year"})
OUTPUT_FORMATS = frozenset({"list"})
RRF_K = 60  # reciprocal rank fusion constant


class SearchInputError(ValueError):
    """Raised when a rebuilt web.search call is outside the bounded contract."""


@dataclass(frozen=True)
class SearchQuery:
    query: str
    limit: int = DEFAULT_SEARCH_LIMIT
    time_range: str | None = None
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()
    min_score: float = 0.0
    auto_fetch: int = 0
    format: str = "list"


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    score: float = 0.0
    freshness: str | None = None
    domain: str | None = None
    fetch_status: str | None = None
    artifact_uri: str | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            object.__setattr__(self, "title", self.domain or self.url)
        if len(self.title) > 200:
            object.__setattr__(self, "title", self.title[:200])
        if len(self.snippet) > 1_000:
            object.__setattr__(self, "snippet", self.snippet[:1_000])


@dataclass(frozen=True)
class SearchRunResult:
    hits: tuple[SearchHit, ...]
    provider: str
    fetched_count: int
    expanded_query_count: int
    truncated: bool
    degraded: bool = False


def parse_search_query(arguments: object) -> SearchQuery:
    if not isinstance(arguments, dict):
        raise SearchInputError("web.search arguments must be an object")
    extra = set(arguments) - {
        "query",
        "limit",
        "time_range",
        "include_domains",
        "exclude_domains",
        "min_score",
        "auto_fetch",
        "format",
    }
    if extra:
        raise SearchInputError(
            f"web.search received unsupported arguments: {', '.join(sorted(extra))}"
        )
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise SearchInputError("web.search query must be a non-blank string")
    query = query.strip()
    if len(query) > MAX_SEARCH_QUERY_CHARS:
        raise SearchInputError(
            f"web.search query must not exceed {MAX_SEARCH_QUERY_CHARS} characters"
        )
    limit = arguments.get("limit", DEFAULT_SEARCH_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise SearchInputError("web.search limit must be an integer")
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise SearchInputError(f"web.search limit must be between 1 and {MAX_SEARCH_LIMIT}")
    time_range = arguments.get("time_range")
    if time_range is not None and time_range not in TIME_RANGES:
        raise SearchInputError("web.search time_range must be one of day/week/month/year")
    include_domains = _domain_list(arguments.get("include_domains"), "include_domains")
    exclude_domains = _domain_list(arguments.get("exclude_domains"), "exclude_domains")
    min_score = arguments.get("min_score", 0.0)
    if not isinstance(min_score, int | float) or isinstance(min_score, bool):
        raise SearchInputError("web.search min_score must be a number")
    min_score = float(min_score)
    if not 0.0 <= min_score <= 1.0:
        raise SearchInputError("web.search min_score must be within [0.0, 1.0]")
    auto_fetch = arguments.get("auto_fetch", 0)
    if isinstance(auto_fetch, bool) or not isinstance(auto_fetch, int):
        raise SearchInputError("web.search auto_fetch must be an integer")
    if not 0 <= auto_fetch <= MAX_SEARCH_LIMIT:
        raise SearchInputError("web.search auto_fetch must be between 0 and 20")
    fmt = arguments.get("format", "list")
    if fmt not in OUTPUT_FORMATS:
        raise SearchInputError("web.search format must be 'list'")
    return SearchQuery(
        query=query,
        limit=limit,
        time_range=time_range,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
        min_score=min_score,
        auto_fetch=auto_fetch,
        format=fmt,
    )


def _domain_list(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SearchInputError(f"web.search {field_name} must be a list of strings")
    domains: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SearchInputError(f"web.search {field_name} entries must be non-blank strings")
        domains.append(item.strip().lower())
        if len(domains) > MAX_DOMAIN_FILTERS:
            raise SearchInputError(f"web.search {field_name} exceeds {MAX_DOMAIN_FILTERS} entries")
    return tuple(domains)


class SearchProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def search(self, query: SearchQuery, *, limit: int) -> tuple[SearchHit, ...]: ...


class SearchProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, SearchProvider] = {}
        self._default: SearchProvider | None = None

    def register(self, provider: SearchProvider, *, default: bool = False) -> None:
        if provider.name in self._providers:
            raise ValueError(f"search provider already registered: {provider.name}")
        self._providers[provider.name] = provider
        if default or self._default is None:
            self._default = provider

    def get(self, name: str | None) -> SearchProvider:
        if name is not None:
            if name not in self._providers:
                raise KeyError(f"unknown search provider: {name}")
            return self._providers[name]
        if self._default is None:
            raise KeyError("no search provider registered")
        return self._default

    @property
    def default(self) -> SearchProvider | None:
        return self._default

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


# ---------------------------------------------------------------------------
# Quality levers (WEB-PIPE-SEARCH-Q-01)
# ---------------------------------------------------------------------------


def expand_query(query: SearchQuery) -> tuple[str, ...]:
    """Deterministic multi-query expansion: the raw query plus a variant that
    drops stop-words, so RRF can fuse slightly different result orderings."""
    raw = query.query
    stop = {
        "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is",
        "are", "what", "how", "why", "who", "when", "which",
    }
    kept = [word for word in raw.split() if word.lower() not in stop]
    variant = " ".join(kept).strip()
    if variant and variant.lower() != raw.lower():
        return (raw, variant)
    return (raw,)


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[SearchHit]],
    *,
    k: int = RRF_K,
) -> tuple[SearchHit, ...]:
    """Fuse multiple ranked result lists by reciprocal rank fusion."""
    scores: dict[str, float] = {}
    best: dict[str, SearchHit] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked):
            scores[hit.url] = scores.get(hit.url, 0.0) + 1.0 / (k + rank + 1)
            best.setdefault(hit.url, hit)
    fused = sorted(best.values(), key=lambda hit: scores[hit.url], reverse=True)
    return tuple(
        SearchHit(
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            score=scores[hit.url],
            freshness=hit.freshness,
            domain=hit.domain,
        )
        for hit in fused
    )


def keyword_coverage_score(query_text: str, *fields: str) -> float:
    """Fraction of query terms present in the joined fields (0..1)."""
    terms = {word.lower().strip(".,;:!?\"'()") for word in query_text.split()}
    terms.discard("")
    if not terms:
        return 0.0
    haystack = " ".join(fields).lower()
    hits = sum(1 for term in terms if term in haystack)
    return hits / len(terms)


def rerank_hits(hits: Sequence[SearchHit], query_text: str) -> tuple[SearchHit, ...]:
    scored = sorted(
        hits,
        key=lambda hit: keyword_coverage_score(query_text, hit.title, hit.snippet),
        reverse=True,
    )
    return tuple(scored)


def apply_filters(
    hits: Sequence[SearchHit], query: SearchQuery
) -> tuple[SearchHit, ...]:
    filtered: list[SearchHit] = []
    for hit in hits:
        domain = (hit.domain or _hostname_of(hit.url) or "").lower()
        if query.include_domains and not any(
            domain == inc or domain.endswith("." + inc) for inc in query.include_domains
        ):
            continue
        if any(domain == exc or domain.endswith("." + exc) for exc in query.exclude_domains):
            continue
        filtered.append(hit)
    return tuple(filtered)


def _hostname_of(url: str) -> str | None:
    try:
        return parse_web_target(url).hostname
    except WebTargetError:
        return None


# ---------------------------------------------------------------------------
# Pipeline + tool
# ---------------------------------------------------------------------------

#: Injectable fetcher for the search->fetch->rerank loop: url -> clean text.
#: Returns None when the URL cannot be fetched (the loop degrades gracefully).
SearchFetcher = Callable[[str], str | None]


@dataclass(frozen=True)
class SearchPipeline:
    registry: SearchProviderRegistry
    fetcher: SearchFetcher | None = None

    def run(self, query: SearchQuery, *, provider_name: str | None = None) -> SearchRunResult:
        provider = self.registry.get(provider_name)
        expanded = expand_query(query)
        ranked_lists: list[tuple[SearchHit, ...]] = []
        for variant in expanded:
            variant_query = SearchQuery(
                query=variant,
                limit=max(query.limit, DEFAULT_SEARCH_LIMIT),
                time_range=query.time_range,
                include_domains=query.include_domains,
                exclude_domains=query.exclude_domains,
            )
            ranked_lists.append(provider.search(variant_query, limit=variant_query.limit))
        fused = reciprocal_rank_fusion(ranked_lists) if len(ranked_lists) > 1 else (
            ranked_lists[0] if ranked_lists else ()
        )
        reranked = rerank_hits(fused, query.query)
        filtered = apply_filters(reranked, query)
        fetched_count = 0
        if query.auto_fetch > 0 and self.fetcher is not None:
            filtered = self._refetch_and_rerank(filtered, query)
            fetched_count = sum(1 for hit in filtered if hit.fetch_status == "fetched")
        capped = filtered[: query.limit]
        truncated = len(filtered) > query.limit
        final = tuple(hit for hit in capped if hit.score >= query.min_score)
        return SearchRunResult(
            hits=final,
            provider=provider.name,
            fetched_count=fetched_count,
            expanded_query_count=len(expanded),
            truncated=truncated,
            degraded=not provider.available,
        )

    def _refetch_and_rerank(
        self, hits: tuple[SearchHit, ...], query: SearchQuery
    ) -> tuple[SearchHit, ...]:
        candidates = list(hits[: query.auto_fetch])
        tail = list(hits[query.auto_fetch :])
        scored: list[tuple[float, SearchHit]] = []
        for hit in candidates:
            assert self.fetcher is not None
            text = self.fetcher(hit.url)
            if text is None:
                scored.append((hit.score, _with_fetch_status(hit, "failed")))
                continue
            coverage = keyword_coverage_score(query.query, text)
            blended = 0.5 * hit.score + 0.5 * coverage
            scored.append(
                (blended, _with_fetch_status(hit, "fetched"))
            )
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return tuple(hit for _, hit in scored) + tuple(tail)


def _with_fetch_status(hit: SearchHit, status: str) -> SearchHit:
    return SearchHit(
        title=hit.title,
        url=hit.url,
        snippet=hit.snippet,
        score=hit.score,
        freshness=hit.freshness,
        domain=hit.domain,
        fetch_status=status,
        artifact_uri=hit.artifact_uri,
    )


web_search_v2_contract = ToolContract(
    name="web.search",
    capability_version="2",
    description=(
        "Search an approved Web provider for ranked source candidates with "
        "optional freshness/domain filters and search->fetch reranking. "
        "Results are untrusted and are not opened automatically."
    ),
    required_arguments=("query",),
    argument_properties={
        "query": {"type": "string", "minLength": 1, "maxLength": MAX_SEARCH_QUERY_CHARS},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_LIMIT},
        "time_range": {"type": "string", "enum": sorted(TIME_RANGES)},
        "include_domains": {"type": "array", "items": {"type": "string"}},
        "exclude_domains": {"type": "array", "items": {"type": "string"}},
        "min_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "auto_fetch": {"type": "integer", "minimum": 0, "maximum": MAX_SEARCH_LIMIT},
        "format": {"type": "string", "enum": sorted(OUTPUT_FORMATS)},
    },
)


@dataclass(frozen=True)
class SearchPipelineTool:
    pipeline: SearchPipeline
    provider_name: str | None = None

    @property
    def contract(self) -> ToolContract:
        return web_search_v2_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        try:
            query = parse_search_query(tool_call.arguments)
        except SearchInputError as exc:
            return _failure(tool_call, reason="invalid_search_input", detail=str(exc))
        try:
            result = self.pipeline.run(query, provider_name=self.provider_name)
        except KeyError as exc:
            return _failure(tool_call, reason="provider_unavailable", detail=str(exc))
        lines = ["[UNTRUSTED EXTERNAL SEARCH RESULTS]"]
        for index, hit in enumerate(result.hits, start=1):
            lines.extend((f"{index}. {hit.title}", hit.url, hit.snippet))
        envelope = WebResultEnvelope(
            provider=result.provider,
            provider_version=None,
            capability_version=web_search_v2_contract.capability_version,
            fetched_at=_now_iso(),
            canonical_url="web.search",
            truncation_scope=(
                TruncationScope.NONE if not result.truncated else TruncationScope.PROJECTION
            ),
            truncated=result.truncated,
            degraded=result.degraded,
            extra={
                "provider": result.provider,
                "result_count": len(result.hits),
                "fetched_count": result.fetched_count,
                "expanded_query_count": result.expanded_query_count,
                "min_score": query.min_score,
                "hits": [
                    {
                        "title": hit.title,
                        "url": hit.url,
                        "snippet": hit.snippet,
                        "score": round(hit.score, 4),
                        "domain": hit.domain,
                        "freshness": hit.freshness,
                        "fetch_status": hit.fetch_status,
                    }
                    for hit in result.hits
                ],
            },
        )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="\n".join(lines),
            metadata={
                "route": "search_pipeline",
                "provider": result.provider,
                "result_count": len(result.hits),
                "fetched_count": result.fetched_count,
                "expanded_query_count": result.expanded_query_count,
                "truncated": result.truncated,
                "degraded": result.degraded,
                "untrusted_external_content": True,
                "web_envelope": envelope.to_metadata(),
            },
        )


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


def _failure(tool_call: ToolCall, *, reason: str, detail: str) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        metadata={"route": "search_pipeline", "reason": reason, "detail": detail},
    )


__all__ = [
    "MAX_SEARCH_LIMIT",
    "SearchFetcher",
    "SearchHit",
    "SearchInputError",
    "SearchPipeline",
    "SearchPipelineTool",
    "SearchProvider",
    "SearchProviderRegistry",
    "SearchQuery",
    "SearchRunResult",
    "apply_filters",
    "expand_query",
    "keyword_coverage_score",
    "parse_search_query",
    "reciprocal_rank_fusion",
    "rerank_hits",
    "web_search_v2_contract",
]
