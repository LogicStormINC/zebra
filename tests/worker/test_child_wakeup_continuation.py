from datetime import UTC, datetime
from uuid import uuid4

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from zebra_agent_worker.child_wakeup_continuation import (
    recover_child_wakeup_continuation,
)


def test_child_wakeup_recovery_preserves_parent_budget_counters() -> None:
    parent = new_session_id()
    child = str(uuid4())
    tool_call = str(uuid4())
    now = datetime.now(UTC)
    events = [
        SessionEvent.create(
            session_id=parent,
            sequence=0,
            event_type=EventType.SUBAGENT_DELEGATED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "child_task_id": child,
                "tool_name": "agent.research",
                "tool_call_id": tool_call,
                "arguments": {
                    "objective": "Collect evidence",
                    "delegation_reason": "Isolate the bounded research",
                },
                "assistant_message": "Delegating research.",
                "conversation": [],
                "model_calls_used": 7,
                "tool_calls_executed": 11,
            },
            created_at=now,
        ),
        SessionEvent.create(
            session_id=parent,
            sequence=1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.HARNESS,
            payload={
                "command_id": str(uuid4()),
                "session_id": str(parent),
                "kind": "resume",
                "expected_revision": 0,
                "idempotency_key": f"child-wakeup:{parent}",
                "payload": {
                    "child_results": [
                        {
                            "child_task_id": child,
                            "status": "completed",
                            "summary": "Evidence collected.",
                        }
                    ]
                },
                "fingerprint": "a" * 64,
            },
            created_at=now,
        ),
    ]

    recovered = recover_child_wakeup_continuation(events)

    assert recovered is not None
    assert recovered.model_calls_used == 7
    assert recovered.tool_calls_executed == 11
