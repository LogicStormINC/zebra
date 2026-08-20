"""Recover every durable continuation kind for one claimed Session."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_core.domain.events import SessionEvent
from agent_core.ports import EventStorePort

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.child_wakeup_continuation import (
    ChildResultVerifier,
    ChildWakeupContinuation,
    recover_child_wakeup_continuation,
)

__all__ = [
    "ActiveContinuationConflict",
    "ActiveContinuations",
    "build_child_result_verifier",
    "recover_active_continuations",
    "recover_and_start_continuations",
]
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.continuation_lifecycle import start_recovered_continuation
from zebra_agent_worker.continuation_recovery import (
    recover_approved_continuation,
    recover_clarification_continuation,
)
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.recovery import SessionRecoveryService


def build_child_result_verifier(
    delegation_store: Any, projection_store: Any
) -> ChildResultVerifier | None:
    """Fail-closed verifier for wakeup-carried child results.

    Every delivered result must match durable state: a terminal
    delegation link, a matching terminal child projection, and the
    child's OWN terminal event answer — a forged or stale summary is
    rejected before it can enter the parent conversation.
    """

    if delegation_store is None or projection_store is None:
        return None
    get_link = getattr(delegation_store, "get_link", None)
    summary_of = getattr(delegation_store, "child_terminal_summary", None)
    if not callable(get_link) or not callable(summary_of):
        return None

    def verify(child_task_id: str, status: str, summary: str) -> None:
        from uuid import UUID

        from agent_core.domain.identifiers import SessionId, TaskId

        child = TaskId(UUID(str(child_task_id)))
        link = get_link(child)
        if link is None or link.terminal_at is None:
            raise ValueError(
                f"child wakeup result rejected: {child_task_id} has no "
                "terminal delegation link"
            )
        child_session = projection_store.get_session(SessionId(UUID(str(child_task_id))))
        if child_session is None or child_session.status.value != status:
            raise ValueError(
                f"child wakeup result rejected: {child_task_id} status drift"
            )
        trusted = summary_of(child)
        if (trusted or "") != summary:
            raise ValueError(
                f"child wakeup result rejected: {child_task_id} summary "
                "does not match its own terminal event"
            )

    return verify


class ActiveContinuationConflict(ValueError):
    """The Session carries more than one resumable continuation."""


@dataclass(frozen=True)
class ActiveContinuations:
    approved: ApprovedContinuation | None
    clarification: ClarificationContinuation | None
    child_wakeup: ChildWakeupContinuation | None


def recover_active_continuations(
    session_events: list[SessionEvent],
    *,
    child_result_verifier: ChildResultVerifier | None = None,
) -> ActiveContinuations:
    approved = recover_approved_continuation(session_events)
    clarification = recover_clarification_continuation(session_events)
    child_wakeup = recover_child_wakeup_continuation(
        session_events, verifier=child_result_verifier
    )
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
    child_result_verifier: ChildResultVerifier | None = None,
) -> tuple[ClaimedSession, ActiveContinuations]:
    """Recover the active continuation and emit its start Events.

    ``cleanup`` closes the tool gateway when recovery fails so no runtime
    leaks; cleanup failures surface alongside the original error.
    """

    try:
        continuations = recover_active_continuations(
            session_events, child_result_verifier=child_result_verifier
        )
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
