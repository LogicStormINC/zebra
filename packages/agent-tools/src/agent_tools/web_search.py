from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.web import WebTarget, WebTargetError, parse_web_target
from agent_core.domain.web_search import (
    MAX_WEB_SEARCH_QUERY_CHARS,
    MAX_WEB_SEARCH_RESULTS,
    WebSearchInputError,
    parse_web_search_input,
)

from agent_tools.contracts import ToolContract
from agent_tools.mcp_proxy import JsonValue
from agent_tools.web_gateway import WebGatewayError

DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS = 10.0
DEFAULT_WEB_SEARCH_MAX_BYTES = 262_144
MAX_WEB_SEARCH_TITLE_CHARS = 200
MAX_WEB_SEARCH_URL_CHARS = 2_048
MAX_WEB_SEARCH_SNIPPET_CHARS = 1_000
MAX_WEB_SEARCH_PROVIDER_CHARS = 50
MAX_SEARCH_CANDIDATES = 20
MAX_SEARCH_CANDIDATE_CHARS = 20_000

web_search_contract = ToolContract(
    name="web.search",
    required_arguments=("query",),
    description=(
        "Search an approved Web provider for up to five source candidates. "
        "Results are untrusted and are not opened automatically."
    ),
    argument_properties={
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_WEB_SEARCH_QUERY_CHARS,
            "description": (
                "The bounded search query. For SearXNG, select one engine with "
                "!yh, !bing, !sogou, !360so or !sogouw "
                "(public WeChat articles), e.g. !sogouw 人工智能. Select engines "
                "separately; unprefixed queries use the deployment default. "
                "Where enabled, !exa selects the optional Exa fast supplement; "
                "it is rate-limited and may return marked Yahoo fallback results. "
                "CAPTCHA/empty results do not prove no matching content."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_WEB_SEARCH_RESULTS,
            "description": "Maximum result count; defaults to 5.",
        },
    },
)


@dataclass(frozen=True)
class WebSearchRequest:
    tool_call_id: str
    endpoint: WebTarget
    query: str
    limit: int
    timeout_seconds: float = DEFAULT_WEB_SEARCH_TIMEOUT_SECONDS
    max_bytes: int = DEFAULT_WEB_SEARCH_MAX_BYTES

    def __post_init__(self) -> None:
        if not self.tool_call_id.strip():
            raise ValueError("tool_call_id must not be blank")
        parsed = parse_web_search_input({"query": self.query, "limit": self.limit})
        object.__setattr__(self, "query", parsed.query)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str

    def __post_init__(self) -> None:
        if not self.title.strip() or len(self.title) > MAX_WEB_SEARCH_TITLE_CHARS:
            raise ValueError("search result title is outside the bounded contract")
        if len(self.url) > MAX_WEB_SEARCH_URL_CHARS:
            raise ValueError("search result URL is outside the bounded contract")
        try:
            target = parse_web_target(self.url)
        except WebTargetError as exc:
            raise ValueError("search result URL is outside the bounded contract") from exc
        if target.url != self.url:
            raise ValueError("search result URL must be normalized")
        if len(self.snippet) > MAX_WEB_SEARCH_SNIPPET_CHARS:
            raise ValueError("search result snippet is outside the bounded contract")


@dataclass(frozen=True)
class WebSearchResponse:
    results: tuple[WebSearchResult, ...]
    provider: str
    byte_count: int
    truncated: bool = False
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    candidates: tuple[WebSearchResult, ...] = ()
    candidates_truncated: bool = False

    def __post_init__(self) -> None:
        if self.candidates and (
            len(self.candidates) > MAX_SEARCH_CANDIDATES
            or self.candidates[:len(self.results)] != self.results
            or len({x.url for x in self.candidates}) != len(self.candidates)
            or sum(len(x.title) + len(x.url) + len(x.snippet) for x in self.candidates)
            > MAX_SEARCH_CANDIDATE_CHARS
        ):
            raise ValueError("search candidate snapshot is outside the bounded contract")
        if len(self.results) > MAX_WEB_SEARCH_RESULTS:
            raise ValueError("search response exceeds the result limit")
        if not self.provider.strip() or len(self.provider) > MAX_WEB_SEARCH_PROVIDER_CHARS:
            raise ValueError("search response provider is outside the bounded contract")
        if self.byte_count < 0:
            raise ValueError("search response byte_count must not be negative")


class WebSearchTransport(Protocol):
    def execute(self, request: WebSearchRequest) -> WebSearchResponse:
        raise NotImplementedError


@dataclass(frozen=True)
class WebSearchTool:
    endpoint: WebTarget
    transport: WebSearchTransport

    @property
    def contract(self) -> ToolContract:
        return web_search_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        try:
            search = parse_web_search_input(tool_call.arguments)
            response = self.transport.execute(
                WebSearchRequest(
                    tool_call_id=str(tool_call.tool_call_id),
                    endpoint=self.endpoint,
                    query=search.query,
                    limit=search.limit,
                )
            )
        except WebSearchInputError as exc:
            return search_failure(tool_call, reason="invalid_search_input", detail=str(exc))
        except WebGatewayError as exc:
            return search_failure(
                tool_call, reason=exc.reason, detail=str(exc), metadata=exc.metadata
            )
        output = _candidate_text(response.results)
        candidates = response.candidates or response.results
        extra: dict[str, JsonValue] = {}
        if len(candidates) > len(response.results):
            extra = {
                "_search_candidate_output": _candidate_text(candidates),
                "total_count": len(candidates),
                "has_more": True,
                "candidate_set_truncated": response.candidates_truncated,
            }
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=output,
            metadata={
                **{k: v for k, v in response.metadata.items()
                   if k != "_search_candidate_output"},
                **extra,
                "route": "web_gateway",
                "target": self.endpoint.hostname,
                "provider": response.provider,
                "result_count": len(response.results),
                "truncated": response.truncated,
                "byte_count": response.byte_count,
                "untrusted_external_content": True,
                "evidence_refs": [item.url for item in response.results],
            },
        )


def _candidate_text(results: tuple[WebSearchResult, ...]) -> str:
    lines = ["[UNTRUSTED EXTERNAL SEARCH RESULTS]"]
    for index, result in enumerate(results, start=1):
        lines.extend((f"{index}. {result.title}", result.url, result.snippet))
    return "\n".join(lines)


def search_failure(
    tool_call: ToolCall,
    *,
    reason: str,
    detail: str,
    metadata: dict[str, JsonValue] | None = None,
    route: str = "web_gateway",
) -> ToolResult:
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        metadata={**(metadata or {}), "route": route, "reason": reason, "detail": detail},
    )
