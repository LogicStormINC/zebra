"""Execution input recovery: suspended claims, handoffs and the Task view."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId

import zebra_agent_worker.provider_continuation_execution as provider_runtime
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.continuation_lifecycle import restore_suspended_session_claim
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import ExecutedSession, WorkerExecutionError
from zebra_agent_worker.execution_preflight import run_with_stale_retry
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat
from zebra_agent_worker.provider_continuation_execution import (
    resolve_provider_continuation,
)
from zebra_agent_worker.recovery import RecoveredSession
from zebra_agent_worker.session_handoff import recover_worker_handoff
from zebra_agent_worker.task_recovery import RecoveredTask, recover_task
from zebra_agent_worker.workspace_resolution import apply_workspace_resolver


@dataclass(frozen=True)
class RecoveredExecutionInputs:
    claimed: ClaimedSession
    session_events: list[SessionEvent]
    provider_continuation: Any
    cloud_continuation: Any
    task: RecoveredTask
    active_capsule: Any
    recovered_handoff: Any


def execute_claimed_with_stale_retry(
    service: Any,
    claimed: ClaimedSession,
    *,
    started_at: datetime,
    ownership_check: Callable[[], None],
) -> ExecutedSession:
    """Run the claimed execution once; on a stale snapshot re-recover.

    A concurrently persisted event (e.g. the next human message) can
    invalidate the claimed snapshot between claim and preflight: the
    Session, Workspace, Task and context are re-recovered from the
    durable stream instead of executing the stale request (ADR-026 §5).
    """
    session_id = claimed.lease.session_id

    def once(
        recovery: RecoveredSession | None = None,
        _claimed: ClaimedSession = claimed,
    ) -> ExecutedSession:
        effective = _claimed if recovery is None else replace(_claimed, recovery=recovery)
        result: ExecutedSession = service._execute_claimed_session_once(
            effective, started_at=started_at, ownership_check=ownership_check
        )
        return result

    def recover() -> RecoveredSession:
        # Cloud recovery requires the CURRENT lease: the fresh retry stays
        # under the same fence that won the original claim.
        result: RecoveredSession = service._recovery_service.recover_session(
            session_id, worker_lease=claimed.lease
        )
        return result

    return run_with_stale_retry(once, recover=recover, ownership_check=ownership_check)


def recover_execution_inputs(
    *,
    claimed: ClaimedSession,
    session_id: SessionId,
    started_at: datetime,
    cloud_deployment: bool,
    cloud_provider_continuation_factory: Any,
    provider_continuation_store: Any,
    control_service: Any,
    recovery_service: Any,
    event_store: Any,
    context_lifecycle_store: Any,
    handoff_gate: Any,
    artifact_payload_reader: Any,
    workspace_resolver: Any,
) -> RecoveredExecutionInputs:
    cloud_continuation = provider_runtime.cloud_for_session(
        cloud_provider_continuation_factory, session_id
    )
    claimed = restore_suspended_session_claim(
        claimed,
        cloud_deployment=cloud_deployment,
        control_service=control_service,
        recovery_service=recovery_service,
        started_at=started_at,
        event_store=event_store,
    )
    recovered_handoff = recover_worker_handoff(
        handoff_gate,
        session_id,
        fence=claimed.lease.fence,
        recovered_at=started_at,
        release=lambda: None,
    )
    session_events = event_store.list_for_session(session_id)
    active_context = context_lifecycle_store.get_active_capsule(session_id)
    provider_continuation = resolve_provider_continuation(
        cloud_continuation,
        session_events,
        provider_continuation_store,
    )
    try:
        task = recover_task(
            session_events,
            workspace=claimed.recovery.workspace,
            fallback_title=claimed.recovery.session.title,
            attachment_reader=artifact_payload_reader,
            active_capsule=active_context.capsule if active_context else None,
            handoff_evidence=(
                None if recovered_handoff is None else recovered_handoff.runtime_evidence
            ),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise WorkerExecutionError(str(exc)) from exc
    if workspace_resolver is not None:
        task = apply_workspace_resolver(task, workspace_resolver, session_id)
    return RecoveredExecutionInputs(
        claimed=claimed,
        session_events=session_events,
        provider_continuation=provider_continuation,
        cloud_continuation=cloud_continuation,
        task=task,
        active_capsule=active_context.capsule if active_context else None,
        recovered_handoff=recovered_handoff,
    )


def execute_session_with_lease(
    service: Any,
    session_id: SessionId,
    *,
    worker_id: str,
    executed_at: datetime | None = None,
    lease_ttl_seconds: int = 30,
) -> ExecutedSession:
    """Claim under a lease heartbeat, admit, then execute the Session."""
    from datetime import UTC as _UTC  # noqa: PLC0415
    from datetime import datetime as _dt

    started_at = executed_at or _dt.now(_UTC)
    claimed = service._claim_service.claim_session(
        session_id,
        worker_id=worker_id,
        claimed_at=started_at,
        lease_ttl_seconds=lease_ttl_seconds,
    )
    with LeaseHeartbeat(
        service._claim_service,
        claimed.lease,
        lease_ttl_seconds=lease_ttl_seconds,
    ) as heartbeat:
        resumed = service._resume_service.require_resumable(
            claimed,
            release_on_failure=False,
        )
        heartbeat.require_owned()
        return execute_claimed_with_stale_retry(
            service,
            resumed.claimed,
            started_at=started_at,
            ownership_check=heartbeat.require_owned,
        )


def persist_runtime_cleanup_failure(
    *,
    recorder: DurableHarnessEventRecorder,
    error: Exception,
    target: Literal["runtime", "tool_gateway"],
    created_at: datetime,
) -> SessionEvent:
    """Persist cleanup failure evidence without changing Session status."""

    recorder.refresh_tail()
    event = SessionEvent.create(
        session_id=recorder.session.session_id,
        sequence=recorder.next_sequence,
        event_type=EventType.RUNTIME_CLEANUP_FAILED,
        actor=EventActor.SYSTEM,
        payload={
            "target": target,
            "error_type": type(error).__name__,
            "attempt_number": 1,
        },
        idempotency_key=(f"runtime-cleanup-failed:{target}:{recorder.session.current_sequence}"),
        created_at=created_at,
    )
    return recorder.append_event(event)
