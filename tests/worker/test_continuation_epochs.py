"""Persisted continuation facts cannot resurrect work from an older control epoch."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id, new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall
from zebra_agent_worker.execution_continuations import recover_active_continuations

NOW = datetime(2026, 10, 28, tzinfo=UTC)
SESSION = new_session_id()


def event(kind, payload=None, actor=EventActor.HARNESS):
    # These are persisted recovery inputs; payload validation is covered at admission.
    return SessionEvent(
        event_id=new_event_id(),
        session_id=SESSION, sequence=0, event_type=kind, actor=actor,
        payload=payload or {}, created_at=NOW,
    )


def pending(kind):
    call = ToolCall(
        tool_call_id=new_tool_call_id(), name="command.run",
        arguments={"command": "pwd"}, created_at=NOW,
    )
    payload = {
        "tool_call_id": str(call.tool_call_id), "tool_name": call.name,
        "arguments": call.arguments, "call_fingerprint": call.approval_fingerprint,
        "assistant_message": "Need evidence", "conversation": [],
        "model_calls_used": 2, "tool_calls_executed": 1,
        "continuation_metadata": {"verification_required": True},
    }
    if kind == "approved":
        return [
            event(EventType.APPROVAL_REQUESTED, payload, EventActor.POLICY),
            event(EventType.APPROVAL_GRANTED, payload, EventActor.USER),
        ]
    if kind == "clarification":
        payload.update(clarification_id=str(call.tool_call_id), question="Which item?")
        return [
            event(EventType.CLARIFICATION_REQUESTED, payload),
            event(EventType.CLARIFICATION_RESPONDED, {
                "clarification_id": str(call.tool_call_id), "content": "First item",
            }, EventActor.USER),
        ]
    child = str(uuid4())
    payload.update(child_task_id=child, tool_name="agent.research")
    return [
        event(EventType.SUBAGENT_DELEGATED, payload),
        event(EventType.SESSION_COMMAND_ACCEPTED, {
            "kind": "resume", "payload": {"child_results": [{
                "child_task_id": child, "status": "completed", "summary": "Evidence",
            }]},
        }),
    ]


def recover(events):
    return recover_active_continuations([
        item.model_copy(update={"sequence": index}) for index, item in enumerate(events)
    ])


BOUNDARIES = [
    (kind, {}) for kind in (
        EventType.TURN_COMPLETED, EventType.TURN_FAILED, EventType.TURN_CANCELLED,
        EventType.SESSION_COMPLETED, EventType.SESSION_FAILED, EventType.SESSION_CANCELLED,
        EventType.USER_MESSAGE_RECEIVED,
    )
] + [
    (EventType.SESSION_SUSPENDED, {"reason": reason})
    for reason in ("user_requested", "execution_storage_contention", "verification_required")
] + [
    (EventType.SESSION_COMMAND_ACCEPTED, {"kind": kind})
    for kind in ("stop", "cancel", "suspend")
]


@pytest.mark.parametrize("kind", ["approved", "clarification", "child_wakeup"])
@pytest.mark.parametrize("boundary,payload", BOUNDARIES)
@pytest.mark.parametrize("receipt_first", [True, False])
def test_unstarted_receipt_cannot_cross_boundary(kind, boundary, payload, receipt_first):
    request, receipt = pending(kind)
    marker = event(boundary, payload)
    events = [request, receipt, marker] if receipt_first else [request, marker, receipt]
    verifier = Mock()
    result = recover_active_continuations(events, child_result_verifier=verifier)
    assert getattr(result, kind) is None
    verifier.assert_not_called()


@pytest.mark.parametrize("kind", ["approved", "clarification", "child_wakeup"])
def test_current_receipt_keeps_identity_counters_and_verification(kind):
    events = pending(kind)
    if kind == "child_wakeup":
        events.insert(1, event(EventType.SESSION_SUSPENDED, {"reason": "waiting_children"}))
    events.append(event(EventType.SESSION_RESUMED, {"reason": "continuation_resolved"}))
    result = getattr(recover(events), kind)
    assert result is not None
    assert str(result.tool_call.tool_call_id) == events[0].payload["tool_call_id"]
    assert result.model_calls_used == 2
    assert result.tool_calls_executed == 1
    assert result.metadata == {"verification_required": True}


@pytest.mark.parametrize("old_kind", ["approved", "clarification", "child_wakeup"])
@pytest.mark.parametrize("new_kind", ["approved", "clarification", "child_wakeup"])
def test_new_turn_does_not_inherit_old_receipt_or_conflict(old_kind, new_kind):
    history = []
    for _ in range(120):
        history.extend(pending(old_kind))
        history.append(event(EventType.TURN_COMPLETED))
        history.append(event(EventType.USER_MESSAGE_RECEIVED))
    current = pending(new_kind)
    result = getattr(recover(history + current), new_kind)
    assert result is not None
    assert str(result.tool_call.tool_call_id) == current[0].payload["tool_call_id"]
