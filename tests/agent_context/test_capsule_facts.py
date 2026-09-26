from datetime import UTC, datetime

from agent_context.capsule_facts import (
    capsule_permission_boundaries,
    capsule_work_facts,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id

NOW = datetime(2026, 9, 22, 1, 0, tzinfo=UTC)


def test_latest_structured_plan_preserves_completed_pending_and_rejected_work() -> None:
    session_id = new_session_id()
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.PLAN_UPDATED,
            actor=EventActor.HARNESS,
            payload={
                "steps": [
                    {"step_id": "old", "content": "obsolete", "status": "pending"},
                ]
            },
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.PLAN_UPDATED,
            actor=EventActor.HARNESS,
            payload={
                "steps": [
                    {"step_id": "done", "content": "inspect root cause", "status": "completed"},
                    {"step_id": "next", "content": "run acceptance", "status": "in_progress"},
                    {"step_id": "later", "content": "deploy", "status": "pending"},
                    {"step_id": "no", "content": "rewrite the runtime", "status": "cancelled"},
                ]
            },
            created_at=NOW,
        ),
    ]

    facts = capsule_work_facts(events)

    assert facts.completed_actions == ("inspect root cause",)
    assert facts.pending_actions == ("run acceptance", "deploy")
    assert facts.rejected_approaches == ("rewrite the runtime",)
    assert "obsolete" not in facts.plan


def test_permission_boundaries_keep_policy_and_approval_outcomes() -> None:
    session_id = new_session_id()
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.POLICY_DECISION_MADE,
            actor=EventActor.POLICY,
            payload={"decision": "require_approval"},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.APPROVAL_REJECTED,
            actor=EventActor.USER,
            payload={"reason": "production write denied"},
            created_at=NOW,
        ),
    ]

    assert capsule_permission_boundaries(events) == (
        "policy_decision_made:require_approval",
        "approval_rejected:production write denied",
    )
