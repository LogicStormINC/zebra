"""Recover every durable continuation kind for one claimed Session."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.events import SessionEvent
from agent_core.ports import EventStorePort

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.child_wakeup_continuation import (
    ChildWakeupContinuation,
    recover_child_wakeup_continuation,
)
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.continuation_lifecycle import start_recovered_continuation
from zebra_agent_worker.continuation_recovery import (
    recover_approved_continuation,
    recover_clarification_continuation,
)
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.recovery import SessionRecoveryService


class ActiveContinuationConflict(ValueError):
    """The Session carries more than one resumable continuation."""


@dataclass(frozen=True)
class ActiveContinuations:
    approved: ApprovedContinuation | None
    clarification: ClarificationContinuation | None
    child_wakeup: ChildWakeupContinuation | None


def recover_active_continuations(
    session_events: list[SessionEvent],
) -> ActiveContinuations:
    approved = recover_approved_continuation(session_events)
    clarification = recover_clarification_continuation(session_events)
    child_wakeup = recover_child_wakeup_continuation(session_events)
    active = [
        continuation
        for continuation in (approved, clarification, child_wakeup)
        if continuation is not None
    ]
    if len(active) > 1:
        raise ActiveContinuationConflict("session has multiple active continuations")
    return ActiveContinuations(
        approved=approved,
        clarification=clarification,
        child_wakeup=child_wakeup,
    )


def recover_and_start_continuations(
    claimed: ClaimedSession,
    *,
    session_events: list[SessionEvent],
    event_store: EventStorePort,
    recovery_service: SessionRecoveryService,
    started_at: datetime,
    recorder: object,
    cleanup: Callable[[], Exception | None],
) -> tuple[ClaimedSession, ActiveContinuations]:
    """Recover the active continuation and emit its start Events.

    ``cleanup`` closes the tool gateway when recovery fails so no runtime
    leaks; cleanup failures surface alongside the original error.
    """

    try:
        continuations = recover_active_continuations(session_events)
    except (ValueError, WorkerExecutionError) as exc:
        cleanup_error = cleanup()
        if cleanup_error is not None:
            raise WorkerExecutionError(
                f"{exc}; runtime cleanup failed: {cleanup_error}"
            ) from cleanup_error
        raise WorkerExecutionError(str(exc)) from exc
    started = start_recovered_continuation(
        claimed,
        continuation=continuations.approved,
        clarification=continuations.clarification,
        event_store=event_store,
        recovery_service=recovery_service,
        started_at=started_at,
        recorder=recorder,  # type: ignore[arg-type]
        child_wakeup=continuations.child_wakeup,
    )
    return started, continuations
