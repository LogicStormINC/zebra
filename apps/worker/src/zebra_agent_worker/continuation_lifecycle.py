from datetime import datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import EventStorePort

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.control import SessionControlError, SessionControlService
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.recovery import SessionRecoveryService


def mark_approved_continuation_started(
    claimed: ClaimedSession,
    *,
    event_store: EventStorePort,
    recovery_service: SessionRecoveryService,
    tool_name: str,
    tool_call_id: str,
    started_at: datetime,
    recorder: DurableHarnessEventRecorder | None = None,
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
        event = SessionEvent.create(
            session_id=claimed.recovery.session.session_id,
            sequence=next_sequence,
            event_type=event_type,
            actor=EventActor.HARNESS,
            payload=payload,
            created_at=started_at,
        )
        if recorder is None:
            event_store.append(event)
        else:
            recorder.append_event(event)
        next_sequence += 1
    return _recovered_claim(claimed, recovery_service)


def mark_completed_continuation_started(
    claimed: ClaimedSession,
    *,
    event_store: EventStorePort,
    recovery_service: SessionRecoveryService,
    tool_name: str,
    tool_call_id: str,
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
                "completed_continuation": True,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
            },
            created_at=started_at,
        )
    )
    return _recovered_claim(claimed, recovery_service)


def mark_clarification_continuation_started(
    claimed: ClaimedSession,
    *,
    event_store: EventStorePort,
    recovery_service: SessionRecoveryService,
    clarification_id: str,
    started_at: datetime,
    recorder: DurableHarnessEventRecorder | None = None,
) -> ClaimedSession:
    event = SessionEvent.create(
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
    if recorder is None:
        event_store.append(event)
    else:
        recorder.append_event(event)
    return _recovered_claim(claimed, recovery_service)


def restore_suspended_session_claim(
    claimed: ClaimedSession,
    *,
    cloud_deployment: bool,
    control_service: SessionControlService,
    recovery_service: SessionRecoveryService,
    started_at: datetime,
) -> ClaimedSession:
    """Restore a suspended local Session, or fail closed on the cloud Worker."""
    if claimed.recovery.session.status is not SessionStatus.SUSPENDED:
        return claimed
    if cloud_deployment:
        raise WorkerExecutionError(
            "cloud suspended-session restoration is not supported by the default Worker"
        )
    try:
        restored = control_service.restore_suspended_workspace(
            claimed.lease.session_id,
            resumed_at=started_at,
        )
    except SessionControlError as exc:
        raise WorkerExecutionError(str(exc)) from exc
    if restored is None:
        return claimed
    return _recovered_claim(claimed, recovery_service)


def start_recovered_continuation(
    claimed: ClaimedSession,
    *,
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
    event_store: EventStorePort,
    recovery_service: SessionRecoveryService,
    started_at: datetime,
    recorder: DurableHarnessEventRecorder | None = None,
) -> ClaimedSession:
    """Emit the continuation start Events for the recovered active continuation."""
    if continuation is not None and continuation.completed_output is not None:
        return mark_completed_continuation_started(
            claimed,
            event_store=event_store,
            recovery_service=recovery_service,
            tool_name=continuation.tool_call.name,
            tool_call_id=str(continuation.tool_call.tool_call_id),
            started_at=started_at,
        )
    if continuation is not None:
        return mark_approved_continuation_started(
            claimed,
            event_store=event_store,
            recovery_service=recovery_service,
            tool_name=continuation.tool_call.name,
            tool_call_id=str(continuation.tool_call.tool_call_id),
            started_at=started_at,
            recorder=recorder,
        )
    if clarification is not None:
        return mark_clarification_continuation_started(
            claimed,
            event_store=event_store,
            recovery_service=recovery_service,
            clarification_id=str(clarification.tool_call.tool_call_id),
            started_at=started_at,
            recorder=recorder,
        )
    return claimed


def _recovered_claim(
    claimed: ClaimedSession,
    recovery_service: SessionRecoveryService,
) -> ClaimedSession:
    return ClaimedSession(
        recovery=recovery_service.recover_session(
            claimed.recovery.session.session_id,
            worker_lease=claimed.lease,
        ),
        lease=claimed.lease,
    )
