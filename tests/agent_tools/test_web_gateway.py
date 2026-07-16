from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.domain.web import parse_web_target
from agent_tools.web_gateway import (
    WebFetchTool,
    WebGatewayRequest,
    WebGatewayResponse,
)


@dataclass
class FakeWebTransport:
    requests: list[WebGatewayRequest] = field(default_factory=list)

    def execute(self, request: WebGatewayRequest) -> WebGatewayResponse:
        self.requests.append(request)
        return WebGatewayResponse(
            text="ZEBRA WEB OK",
            status_code=200,
            content_type="text/plain",
            byte_count=12,
        )


def test_web_fetch_returns_labeled_untrusted_content_and_safe_metadata() -> None:
    transport = FakeWebTransport()
    result = WebFetchTool(transport).handle(_tool_call("https://docs.example.com/info"))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == "[UNTRUSTED EXTERNAL CONTENT]\nZEBRA WEB OK"
    assert len(transport.requests) == 1
    assert result.metadata == {
        "route": "web_gateway",
        "target": "docs.example.com",
        "url": "https://docs.example.com/info",
        "status_code": 200,
        "content_type": "text/plain",
        "byte_count": 12,
        "untrusted_external_content": True,
    }


def test_web_fetch_rejects_invalid_target_before_transport() -> None:
    transport = FakeWebTransport()
    result = WebFetchTool(transport).handle(_tool_call("http://docs.example.com"))

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "invalid_web_target"
    assert transport.requests == []


def test_web_gateway_request_rejects_invalid_output_budget() -> None:
    with pytest.raises(ValueError, match="max_output_bytes"):
        WebGatewayRequest(
            tool_call_id="call-invalid",
            target=parse_web_target("https://docs.example.com"),
            max_output_bytes=0,
        )


def _tool_call(url: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="web.fetch",
        arguments={"url": url},
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
