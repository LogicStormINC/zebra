from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_runtime import McpElicitationBridge, McpElicitationDisabledError

_SCHEMA = {"type": "object", "properties": {"email": {"type": "string"}}}
_REQUESTED_AT = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)


def test_parse_elicitation_create() -> None:
    request = McpElicitationBridge.parse_elicitation_create(
        {"message": "Email?", "requestedSchema": _SCHEMA}
    )
    assert request.message == "Email?"
    assert request.requested_schema == _SCHEMA


def test_parse_elicitation_create_allows_missing_schema() -> None:
    request = McpElicitationBridge.parse_elicitation_create({"message": "Confirm?"})
    assert request.requested_schema is None


def test_parse_rejects_missing_message() -> None:
    with pytest.raises(ValueError, match="non-blank"):
        McpElicitationBridge.parse_elicitation_create({"requestedSchema": _SCHEMA})


def test_build_context_when_enabled_carries_schema() -> None:
    bridge = McpElicitationBridge(enabled=True)
    request = McpElicitationBridge.parse_elicitation_create(
        {"message": "Email?", "requestedSchema": _SCHEMA}
    )
    context = bridge.build_clarification_context(
        request,
        tool_call_id="call-1",
        assistant_message="assistant protocol message",
        requested_at=_REQUESTED_AT,
    )
    assert context.response_schema == _SCHEMA
    assert context.effective_source == "mcp.elicitation"


def test_build_context_when_disabled_rejects() -> None:
    bridge = McpElicitationBridge(enabled=False)
    request = McpElicitationBridge.parse_elicitation_create({"message": "Email?"})
    with pytest.raises(McpElicitationDisabledError):
        bridge.build_clarification_context(
            request,
            tool_call_id="call-1",
            assistant_message="assistant protocol message",
            requested_at=_REQUESTED_AT,
        )


def test_build_elicitation_result_shape() -> None:
    assert McpElicitationBridge.build_elicitation_result("accept", "a@b") == {
        "action": "accept",
        "content": "a@b",
    }
    assert McpElicitationBridge.build_elicitation_result("decline") == {"action": "decline"}
    with pytest.raises(ValueError, match="action"):
        McpElicitationBridge.build_elicitation_result("bogus")
