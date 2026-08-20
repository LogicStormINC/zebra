from datetime import datetime

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import EventStorePort

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.child_wakeup_continuation import ChildWakeupContinuation
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
    event_store: EventStorePort | None = None,
) -> ClaimedSession:
    """Restore a suspended Session, or fail closed on the cloud Worker.

    A logical waiting_children suspension (durable delegation) has no
    runtime snapshot to restore — the cloud Worker resumes it by emitting
    SESSION_RESUMED and re-entering normal execution. Snapshot-based
    suspensions keep the fail-closed cloud refusal.
    """
    if claimed.recovery.session.status is not SessionStatus.SUSPENDED:
        return claimed
    if cloud_deployment:
        if event_store is None:
            raise WorkerExecutionError(
                "cloud suspended-session restoration requires the event store"
            )
        events = event_store.list_for_session(claimed.lease.session_id)
        if not _is_waiting_children_suspension(events):
            raise WorkerExecutionError(
                "cloud suspended-session restoration is not supported by the default Worker"
            )
        if not _has_trusted_child_wakeup(events):
            # A USER resume command cannot substitute for the durable
            # wakeup — without it the parent would re-run from scratch and
            # the delegated results would be lost.
            raise WorkerExecutionError(
                "waiting_children suspension requires the harness wakeup to resume"
            )
        event_store.append(
            SessionEvent.create(
                session_id=claimed.lease.session_id,
                sequence=claimed.recovery.session.current_sequence + 1,
                event_type=EventType.SESSION_RESUMED,
                actor=EventActor.HARNESS,
                payload={"reason": "waiting_children_resolved"},
                created_at=started_at,
            )
        )
        return _recovered_claim(claimed, recovery_service)
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


def _is_waiting_children_suspension(events: list[SessionEvent]) -> bool:
    """True when the live suspension state is a logical waiting_children one."""

    waiting = False
    for event in events:
        if event.event_type is EventType.SESSION_SUSPENDED:
            waiting = event.payload.get("reason") == "waiting_children"
        elif event.event_type in (
            EventType.SESSION_RESUMED,
            EventType.SESSION_COMPLETED,
            EventType.SESSION_FAILED,
            EventType.SESSION_CANCELLED,
        ):
            waiting = False
    return waiting


def _has_trusted_child_wakeup(events: list[SessionEvent]) -> bool:
    """A harness-actor resume command must exist after the last suspension."""

    trusted = False
    for event in events:
        if event.event_type is EventType.SESSION_SUSPENDED:
            trusted = False
        elif (
            event.event_type is EventType.SESSION_COMMAND_ACCEPTED
            and event.actor is EventActor.HARNESS
            and event.payload.get("kind") == "resume"
        ):
            trusted = True
    return trusted


def start_recovered_continuation(
    claimed: ClaimedSession,
    *,
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
    event_store: EventStorePort,
    recovery_service: SessionRecoveryService,
    started_at: datetime,
    recorder: DurableHarnessEventRecorder | None = None,
    child_wakeup: ChildWakeupContinuation | None = None,
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
    if child_wakeup is not None:
        return mark_child_wakeup_continuation_started(
            claimed,
            event_store=event_store,
            recovery_service=recovery_service,
            tool_call_id=str(child_wakeup.tool_call.tool_call_id),
            started_at=started_at,
            recorder=recorder,
        )
    return claimed


def mark_child_wakeup_continuation_started(
    claimed: ClaimedSession,
    *,
    event_store: EventStorePort,
    recovery_service: SessionRecoveryService,
    tool_call_id: str,
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
            "child_wakeup_continuation": True,
            "tool_call_id": tool_call_id,
        },
        created_at=started_at,
    )
    if recorder is None:
        event_store.append(event)
    else:
        recorder.append_event(event)
    return _recovered_claim(claimed, recovery_service)


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
