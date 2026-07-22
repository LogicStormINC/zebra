"""Shared V2 web pipeline provider doubles for worker tests.

Both ``test_approved_continuation`` and ``test_web_pipeline_v2_authority`` need
recording Fetch/Search providers to assert execute-once semantics without real
network I/O. Centralizing them avoids circular imports between the two test
modules (which already share gateway/session helpers).
"""

from __future__ import annotations

from agent_tools.search_pipeline import SearchHit
from agent_tools.web_crawl import FetchRequest, FetchResult


class RecordingFetchProvider:
    """V2 FetchProvider double: records the request, returns canned content."""

    def __init__(self) -> None:
        self.requests: list[FetchRequest] = []

    @property
    def name(self) -> str:
        return "recording_fetch"

    @property
    def available(self) -> bool:
        return True

    def fetch(self, request: FetchRequest) -> FetchResult:
        self.requests.append(request)
        return FetchResult(
            requested_url=request.url,
            final_url=request.url,
            clean_markdown="authorized-web-output-v2",
            fetch_mode="http",
            complete=True,
            content_type="text/plain",
            wire_bytes=19,
            decoded_bytes=19,
        )


class RecordingSearchProvider:
    """V2 SearchProvider double: records queries + the configured endpoint."""

    def __init__(self, *, endpoint: str, use_system_proxy: bool = False) -> None:
        self.endpoint = endpoint
        self.queries: list[str] = []

    @property
    def name(self) -> str:
        return "recording_search"

    @property
    def available(self) -> bool:
        return True

    def search(self, query, *, limit: int):  # type: ignore[no-untyped-def]
        self.queries.append(query.query)
        return (
            SearchHit(
                title="Approved result",
                url="https://docs.example.com/result",
                snippet="authorized-search-output-v2",
                domain="docs.example.com",
            ),
        )
