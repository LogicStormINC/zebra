from datetime import UTC, datetime

import pytest
from agent_core.domain.clarifications import (
    DEFAULT_CLARIFICATION_SOURCE,
    MCP_ELICITATION_SOURCE,
    ClarificationContext,
)

_REQUESTED_AT = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
_SCHEMA = {"type": "object", "properties": {"email": {"type": "string"}}}


def test_from_elicitation_builds_context_with_schema_and_source() -> None:
    context = ClarificationContext.from_elicitation(
        message="Which email should I use?",
        requested_schema=_SCHEMA,
        tool_call_id="call-1",
        assistant_message="assistant protocol message",
        requested_at=_REQUESTED_AT,
    )
    mapping = context.to_mapping()
    assert mapping["response_schema"] == _SCHEMA
    assert mapping["elicitation_source"] == MCP_ELICITATION_SOURCE
    assert context.effective_source == MCP_ELICITATION_SOURCE


def test_agent_clarify_context_omits_schema_fields() -> None:
    context = ClarificationContext(
        clarification_id="c",
        tool_call_id="c",
        question="Which audience?",
        choices=("Operators",),
        assistant_message="assistant protocol message",
        requested_at=_REQUESTED_AT,
    )
    mapping = context.to_mapping()
    assert "response_schema" not in mapping
    assert "elicitation_source" not in mapping
    assert context.effective_source == DEFAULT_CLARIFICATION_SOURCE


def test_from_elicitation_rejects_blank_message() -> None:
    with pytest.raises(ValueError, match="non-blank"):
        ClarificationContext.from_elicitation(
            message="   ",
            requested_schema=None,
            tool_call_id="call-1",
            assistant_message="assistant protocol message",
            requested_at=_REQUESTED_AT,
        )


def test_response_schema_size_is_bounded() -> None:
    oversized = {"type": "object", "properties": {f"k{i}": {"type": "string"} for i in range(2000)}}
    with pytest.raises(ValueError, match="size limit"):
        ClarificationContext.from_elicitation(
            message="Too big",
            requested_schema=oversized,
            tool_call_id="call-1",
            assistant_message="assistant protocol message",
            requested_at=_REQUESTED_AT,
        )
