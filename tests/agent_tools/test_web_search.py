from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.domain.web import parse_web_target
from agent_tools.web_search import (
    WebSearchRequest,
    WebSearchResponse,
    WebSearchResult,
    WebSearchTool,
)


@dataclass
class FakeSearchTransport:
    requests: list[WebSearchRequest] = field(default_factory=list)

    def execute(self, request: WebSearchRequest) -> WebSearchResponse:
        self.requests.append(request)
        return WebSearchResponse(
            results=(
                WebSearchResult(
                    title="Zebra result",
                    url="https://docs.example.com/result",
                    snippet="Bounded evidence.",
                ),
            ),
            provider="searxng",
            byte_count=128,
        )


def test_web_search_returns_untrusted_results_and_safe_metadata() -> None:
    transport = FakeSearchTransport()
    tool = WebSearchTool(parse_web_target("https://search.example.com/search"), transport)

    result = tool.handle(_tool_call({"query": " zebra agent ", "limit": 1}))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == (
        "[UNTRUSTED EXTERNAL SEARCH RESULTS]\n"
        "1. Zebra result\nhttps://docs.example.com/result\nBounded evidence."
    )
    assert transport.requests[0].query == "zebra agent"
    assert result.metadata == {
        "route": "web_gateway",
        "target": "search.example.com",
        "provider": "searxng",
        "result_count": 1,
        "truncated": False,
        "byte_count": 128,
        "untrusted_external_content": True,
    }


@pytest.mark.parametrize(
    "arguments",
    (
        {},
        {"query": " "},
        {"query": "x" * 501},
        {"query": "zebra", "limit": 0},
        {"query": "zebra", "limit": 6},
        {"query": "zebra", "limit": True},
        {"query": "zebra", "extra": "no"},
    ),
)
def test_web_search_rejects_invalid_input_before_transport(
    arguments: dict[str, object],
) -> None:
    transport = FakeSearchTransport()
    tool = WebSearchTool(parse_web_target("https://search.example.com/search"), transport)

    result = tool.handle(_tool_call(arguments))

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "invalid_search_input"
    assert transport.requests == []


def _tool_call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.search",
        arguments=arguments,
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
