from datetime import UTC, datetime

import pytest
from agent_core.application.approvals import (
    ApprovalDecisionAction,
    ApprovalDecisionCommand,
    ApprovalDecisionService,
)
from agent_core.domain.events import EventType
from agent_core.domain.sessions import Session, SessionStatus


def _waiting_session() -> Session:
    created_at = datetime(2026, 6, 22, 16, 0, tzinfo=UTC)
    return Session.create(title="approval", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 3,
            "updated_at": created_at,
        }
    )


def test_approval_decision_service_builds_granted_event() -> None:
    session = _waiting_session()
    decided_at = datetime(2026, 6, 22, 16, 1, tzinfo=UTC)

    event = ApprovalDecisionService().build_event(
        session=session,
        next_sequence=4,
        command=ApprovalDecisionCommand(
            action=ApprovalDecisionAction.GRANT,
            operator="alice",
            reason="safe to continue",
            created_at=decided_at,
        ),
    )

    assert event.event_type is EventType.APPROVAL_GRANTED
    assert event.sequence == 4
    assert event.created_at == decided_at
    assert event.payload == {
        "operator": "alice",
        "reason": "safe to continue",
    }


def test_approval_decision_service_builds_rejected_event() -> None:
    event = ApprovalDecisionService().build_event(
        session=_waiting_session(),
        next_sequence=4,
        command=ApprovalDecisionCommand(
            action=ApprovalDecisionAction.REJECT,
            operator="bob",
            reason="too risky",
        ),
    )

    assert event.event_type is EventType.APPROVAL_REJECTED
    assert event.payload["operator"] == "bob"


def test_approval_decision_service_rejects_non_waiting_session() -> None:
    session = Session.create(
        title="running",
        created_at=datetime(2026, 6, 22, 16, 0, tzinfo=UTC),
    ).transition_to(
        SessionStatus.READY,
        updated_at=datetime(2026, 6, 22, 16, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="waiting approval"):
        ApprovalDecisionService().build_event(
            session=session,
            next_sequence=1,
            command=ApprovalDecisionCommand(
                action=ApprovalDecisionAction.GRANT,
                operator="alice",
                reason="safe",
            ),
        )


def test_approval_decision_service_rejects_non_contiguous_sequence() -> None:
    with pytest.raises(ValueError, match="sequence must follow"):
        ApprovalDecisionService().build_event(
            session=_waiting_session(),
            next_sequence=9,
            command=ApprovalDecisionCommand(
                action=ApprovalDecisionAction.REJECT,
                operator="alice",
                reason="unsafe",
            ),
        )
