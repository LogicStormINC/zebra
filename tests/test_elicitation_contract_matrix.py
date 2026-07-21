from __future__ import annotations

from datetime import UTC, datetime

from agent_core.application.session_projection import _clarification_context_from_event
from agent_core.contracts.events import ClarificationRequestedPayload
from agent_core.domain.clarifications import ClarificationContext
from agent_core.domain.events import EventActor, EventType, SessionEvent

_REQUESTED_AT = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
_SCHEMA = {"type": "object", "properties": {"email": {"type": "string"}}}


def _payload_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "attempt_number": 1,
        "clarification_id": "call-1",
        "tool_call_id": "call-1",
        "question": "Which email?",
        "assistant_message": "assistant protocol message",
        "conversation": [],
        "model_calls_used": 0,
        "tool_calls_executed": 0,
    }
    base.update(overrides)
    return base


def test_payload_carries_response_schema_for_elicitation() -> None:
    payload = ClarificationRequestedPayload(
        **_payload_kwargs(response_schema=_SCHEMA, elicitation_source="mcp.elicitation")
    )
    dumped = payload.model_dump(mode="json")
    assert dumped["response_schema"] == _SCHEMA
    assert dumped["elicitation_source"] == "mcp.elicitation"


def test_payload_omits_schema_fields_for_agent_clarify() -> None:
    payload = ClarificationRequestedPayload(**_payload_kwargs())
    dumped = payload.model_dump(mode="json")
    assert "response_schema" not in dumped
    assert "elicitation_source" not in dumped


def test_projection_rebuild_preserves_elicitation_schema() -> None:
    context = ClarificationContext.from_elicitation(
        message="Which email?",
        requested_schema=_SCHEMA,
        tool_call_id="call-1",
        assistant_message="assistant protocol message",
        requested_at=_REQUESTED_AT,
    )
    payload = dict(context.to_mapping())
    payload.pop("requested_at", None)
    event = SessionEvent.create(
        session_id="00000000-0000-0000-0000-000000000001",
        sequence=0,
        event_type=EventType.CLARIFICATION_REQUESTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            **payload,
            "conversation": [],
            "model_calls_used": 0,
            "tool_calls_executed": 0,
        },
        created_at=_REQUESTED_AT,
    )
    rebuilt = _clarification_context_from_event(event)
    assert rebuilt is not None
    assert rebuilt.response_schema == _SCHEMA
    assert rebuilt.effective_source == "mcp.elicitation"
