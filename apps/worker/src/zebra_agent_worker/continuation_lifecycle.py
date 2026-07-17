from datetime import datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import SQLiteEventStore

from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.recovery import SessionRecoveryService


def mark_approved_continuation_started(
    claimed: ClaimedSession,
    *,
    event_store: SQLiteEventStore,
    recovery_service: SessionRecoveryService,
    tool_name: str,
    tool_call_id: str,
    started_at: datetime,
) -> ClaimedSession:
    next_sequence = claimed.recovery.session.current_sequence + 1
    for event_type, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (
            EventType.TOOL_EXECUTION_STARTED,
            {
                "attempt_number": 1,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "approval_continuation": True,
            },
        ),
    ):
        event_store.append(
            SessionEvent.create(
                session_id=claimed.recovery.session.session_id,
                sequence=next_sequence,
                event_type=event_type,
                actor=EventActor.HARNESS,
                payload=payload,
                created_at=started_at,
            )
        )
        next_sequence += 1
    return _recovered_claim(claimed, recovery_service)


def mark_clarification_continuation_started(
    claimed: ClaimedSession,
    *,
    event_store: SQLiteEventStore,
    recovery_service: SessionRecoveryService,
    clarification_id: str,
    started_at: datetime,
) -> ClaimedSession:
    event_store.append(
        SessionEvent.create(
            session_id=claimed.recovery.session.session_id,
            sequence=claimed.recovery.session.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "clarification_continuation": True,
                "clarification_id": clarification_id,
            },
            created_at=started_at,
        )
    )
    return _recovered_claim(claimed, recovery_service)


def _recovered_claim(
    claimed: ClaimedSession,
    recovery_service: SessionRecoveryService,
) -> ClaimedSession:
    return ClaimedSession(
        recovery=recovery_service.recover_session(claimed.recovery.session.session_id),
        lease=claimed.lease,
    )
