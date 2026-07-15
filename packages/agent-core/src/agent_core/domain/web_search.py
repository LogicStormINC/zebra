from __future__ import annotations

from dataclasses import dataclass

MAX_WEB_SEARCH_QUERY_CHARS = 500
MAX_WEB_SEARCH_RESULTS = 5


class WebSearchInputError(ValueError):
    """Raised when a Web search call is outside the bounded contract."""


@dataclass(frozen=True)
class WebSearchInput:
    query: str
    limit: int


def parse_web_search_input(arguments: object) -> WebSearchInput:
    if not isinstance(arguments, dict):
        raise WebSearchInputError("web.search arguments must be an object")
    extra = set(arguments) - {"query", "limit"}
    if extra:
        raise WebSearchInputError(
            f"web.search received unsupported arguments: {', '.join(sorted(extra))}"
        )
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise WebSearchInputError("web.search query must be a non-blank string")
    normalized_query = query.strip()
    if len(normalized_query) > MAX_WEB_SEARCH_QUERY_CHARS:
        raise WebSearchInputError(
            f"web.search query must not exceed {MAX_WEB_SEARCH_QUERY_CHARS} characters"
        )
    limit = arguments.get("limit", MAX_WEB_SEARCH_RESULTS)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise WebSearchInputError("web.search limit must be an integer")
    if not 1 <= limit <= MAX_WEB_SEARCH_RESULTS:
        raise WebSearchInputError(
            f"web.search limit must be between 1 and {MAX_WEB_SEARCH_RESULTS}"
        )
    return WebSearchInput(query=normalized_query, limit=limit)
