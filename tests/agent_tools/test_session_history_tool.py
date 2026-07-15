from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.session_history import (
    SessionHistoryMode,
    SessionHistoryRequest,
    SessionHistoryResult,
    SessionHistorySummary,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_tools import SessionSearchTool


@dataclass
class FakeHistory:
    requests: list[SessionHistoryRequest] = field(default_factory=list)

    def query(self, request: SessionHistoryRequest) -> SessionHistoryResult:
        self.requests.append(request)
        return SessionHistoryResult(
            mode=request.mode,
            sessions=(
                SessionHistorySummary(
                    session_id="00000000-0000-0000-0000-000000000001",
                    title="Prior task",
                    status="completed",
                    created_at=_at(),
                    updated_at=_at(),
                    snippet="bounded evidence",
                    match_count=1,
                ),
            ),
        )


@pytest.mark.parametrize(
    ("arguments", "mode"),
    (
        ({}, SessionHistoryMode.BROWSE),
        ({"query": " evidence "}, SessionHistoryMode.SEARCH),
        (
            {"session_id": "00000000-0000-0000-0000-000000000001", "offset": 2},
            SessionHistoryMode.READ,
        ),
    ),
)
def test_session_search_infers_bounded_call_shape(
    arguments: dict[str, object], mode: SessionHistoryMode
) -> None:
    history = FakeHistory()
    tool = SessionSearchTool(history, "00000000-0000-0000-0000-000000000002")

    result = tool.handle(_call(arguments))

    assert result.status is ToolCallStatus.EXECUTED
    assert history.requests[0].mode is mode
    assert history.requests[0].current_session_id.endswith("2")
    assert result.output.startswith("[UNTRUSTED HISTORICAL SESSION DATA]")
    assert result.metadata["untrusted_historical_content"] is True


@pytest.mark.parametrize(
    "arguments",
    (
        {"query": "x", "session_id": "00000000-0000-0000-0000-000000000001"},
        {"query": " "},
        {"query": "x" * 501},
        {"session_id": "not-a-uuid"},
        {"offset": 1},
        {"limit": 0},
        {"limit": True},
        {"extra": True},
    ),
)
def test_session_search_rejects_malformed_arguments(arguments: dict[str, object]) -> None:
    history = FakeHistory()

    result = SessionSearchTool(history).handle(_call(arguments))

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "invalid_history_input"
    assert history.requests == []


def _call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="sessions.search",
        arguments=arguments,
        created_at=_at(),
    )


def _at() -> datetime:
    return datetime(2026, 7, 15, tzinfo=UTC)
