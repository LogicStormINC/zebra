"""Execution input recovery: suspended claims, handoffs and the Task view."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Never

from agent_context.capsule import execution_evidence_context
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.runtime import RuntimeCapabilityError
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_core.ports.worker_preparation import PreparationAdvanced
from agent_storage.postgres.connection_scope import postgres_connection_scope

import zebra_agent_worker.provider_continuation_execution as provider_runtime
import zebra_agent_worker.runtime_setup as runtime_setup
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.continuation_lifecycle import restore_suspended_session_claim
from zebra_agent_worker.execution_errors import WorkerPluginSetupUnavailable, log_worker_failure
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import (
    ExecutedSession,
    RetryableWorkerSetupError,
    RuntimeStartupError,
    WorkerExecutionError,
    finalize_worker_setup_failure,
    rebuild_task_index,
)
from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot, run_with_stale_retry
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat
from zebra_agent_worker.progress_recovery import WorkerProgressRecovery, recover_worker_progress
from zebra_agent_worker.provider_continuation_execution import (
    resolve_provider_continuation,
)
from zebra_agent_worker.recovery import RecoveredSession
from zebra_agent_worker.session_handoff import recover_worker_handoff
from zebra_agent_worker.task_recovery import (
    RecoveredTask,
    recover_client_state_evidence,
    recover_task,
)
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
    execution_input_reader: Callable[[WorkerLease], list[SessionEvent]] | None = None

    @property
    def reader(self) -> Callable[[WorkerLease], list[SessionEvent]] | None:
        return self.execution_input_reader


def recover_execution_progress(
    service: Any, claimed: ClaimedSession, ownership_check: Callable[[], None]
) -> WorkerProgressRecovery | None:
    """Explicit Cloud composition requires an admitted, indexed canonical Run."""
    namespace = getattr(service, "_execution_namespace", None)
    if namespace is None:
        return None
    try:
        return recover_worker_progress(
            tasks=service._task_index_store,
            namespace=namespace,
            session_id=claimed.lease.session_id,
            ownership_check=ownership_check,
        )
    except PreparationAdvanced:
        raise
    except (CheckpointNotReady, TimeoutError) as error:
        # A bounded preparation slice is resumable, not a deterministic Task failure.
        raise RetryableWorkerSetupError(str(error)) from error


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
        with (
            postgres_connection_scope(task_io=True)
            if getattr(service, "_execution_namespace", None) is not None
            else nullcontext()
        ):
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
    execution_input_reader: Callable[[WorkerLease], list[SessionEvent]] | None = None,
    execution_input_store: Any = None,
    tasks: Any = None,
    namespace: str | None = None,
    ownership_check: Callable[[], None] | None = None,
    strict_dispatch_configured: bool = False,
) -> RecoveredExecutionInputs:
    if ownership_check is not None:
        ownership_check()
    if execution_input_reader is None and execution_input_store is not None:
        from zebra_agent_worker.execution_input_preparation import recover_execution_input_events

        if tasks is None or namespace is None:
            raise ValueError("execution input preparation requires explicit tasks and namespace")
        if execution_input_store.namespace != namespace:
            raise ValueError("execution input namespace disagrees with explicit composition")

        def execution_input_reader(lease: WorkerLease) -> list[SessionEvent]:
            return recover_execution_input_events(
                store=execution_input_store,
                tasks=tasks,
                lease=lease,
                ownership_check=ownership_check,
            )

    if cloud_deployment and execution_input_reader is None:
        raise RetryableWorkerSetupError("cloud execution requires a bounded execution input reader")
    if execution_input_reader is not None:
        from zebra_agent_worker.execution_input_preparation import ExecutionInputEventView

        event_store = ExecutionInputEventView(event_store, execution_input_reader, claimed.lease)
        # Finish all preparation before suspended-session restoration can append
        # SESSION_RESUMED. The main loop retries only this input phase.
        event_store.list_for_session(session_id)
        if execution_input_store is not None and (
            execution_input_store.read(claimed.lease).state.session_revision
            != claimed.recovery.session.current_sequence
        ):
            raise StaleExecutionSnapshot("execution inputs disagree with claimed Session revision")
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
        events=event_store.list_for_session(session_id) if execution_input_reader else None,
    )
    session_events = event_store.list_for_session(session_id)
    if execution_input_store is not None and (
        execution_input_store.read(claimed.lease).state.session_revision
        != claimed.recovery.session.current_sequence
    ):
        raise StaleExecutionSnapshot("execution inputs disagree with restored Session revision")
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
            client_state_evidence=recover_client_state_evidence(session_events),
        )
        if execution_input_store is not None:
            evidence = execution_input_store.read(claimed.lease).state.evidence
            if evidence is not None:
                task = replace(
                    task,
                    runtime_evidence=(
                        *task.runtime_evidence,
                        execution_evidence_context(evidence),
                    ),
                )
        if task.coverage_admission is not None and not strict_dispatch_configured:
            raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED)
        if workspace_resolver is not None and task.coverage_admission is None:
            task = apply_workspace_resolver(task, workspace_resolver, session_id)
    except CoverageRefusedError as exc:
        raise WorkerExecutionError(
            f"strict coverage refused: {exc.reason.value}", coverage_refusal_reason=exc.reason
        ) from None
    except (OSError, ValueError) as exc:
        raise WorkerExecutionError(str(exc)) from exc
    return RecoveredExecutionInputs(
        claimed=claimed,
        session_events=session_events,
        provider_continuation=provider_continuation,
        cloud_continuation=cloud_continuation,
        task=task,
        active_capsule=active_context.capsule if active_context else None,
        recovered_handoff=recovered_handoff,
        execution_input_reader=execution_input_reader,
    )


def execute_session_with_lease(
    service: Any,
    session_id: SessionId,
    *,
    worker_id: str,
    executed_at: datetime | None = None,
    lease_ttl_seconds: int = 30,
    early_authority_refusal=None,
) -> ExecutedSession:
    """Claim under a lease heartbeat, admit, then execute the Session."""
    from datetime import UTC as _UTC  # noqa: PLC0415
    from datetime import datetime as _dt

    from agent_storage.postgres.erp_workspace_policy import private_activation_enabled
    if private_activation_enabled(getattr(service, '_execution_namespace', None)):
        policy = getattr(service, '_erp_workspace_containment', None)
        if policy is None:
            raise ValueError('private direct execution requires native source policy')
        policy.require(session_id)
        raise WorkerExecutionError('erp_private_requires_modern_handoff')
    started_at = executed_at or _dt.now(_UTC)
    claimed = service._claim_service.claim_session(
        session_id,
        worker_id=worker_id,
        claimed_at=started_at,
        lease_ttl_seconds=lease_ttl_seconds,
    )
    return _execute_with_heartbeat(
        service, claimed, started_at, lease_ttl_seconds, early_authority_refusal
    )


def execute_existing_lease(
    service: Any,
    lease: WorkerLease,
    *,
    executed_at: datetime | None = None,
    lease_ttl_seconds: int = 30,
    early_authority_refusal=None,
) -> ExecutedSession:
    """Recover the supplied fence, never reacquire; transfer cleanup to heartbeat."""
    from datetime import UTC  # noqa: PLC0415

    if not isinstance(lease, WorkerLease):
        raise TypeError("claimed execution requires a WorkerLease")
    started_at = executed_at or datetime.now(UTC)
    try:
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("execution timestamps must be timezone-aware")
        claimed = service._claim_service.recover_lease(
            lease,
            lease_ttl_seconds=lease_ttl_seconds,
        )
    except BaseException as error:
        try:
            service._claim_service.release_lease(lease)
        except Exception as cleanup_error:
            error.add_note(f"lease cleanup failed: {type(cleanup_error).__name__}")
        raise
    return _execute_with_heartbeat(
        service, claimed, started_at, lease_ttl_seconds, early_authority_refusal
    )


def _execute_with_heartbeat(
    service: Any,
    claimed: ClaimedSession,
    started_at: datetime,
    lease_ttl_seconds: int,
    early_authority_refusal=None,
) -> ExecutedSession:
    from zebra_agent_worker.erp_fresh_authority import EarlyFreshRefusal, EarlyFreshUnavailable

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
        try:
            return execute_claimed_with_stale_retry(
                service,
                resumed.claimed,
                started_at=started_at,
                ownership_check=heartbeat.require_owned,
            )
        except (EarlyFreshRefusal, EarlyFreshUnavailable) as refusal:
            heartbeat.require_owned()
            if early_authority_refusal is not None:
                early_authority_refusal(resumed.claimed.lease, refusal)
            raise
        except RetryableWorkerSetupError:
            # Runtime availability is external to the Task. Releasing the
            # lease while retaining READY lets the same durable command resume
            # after the sandbox dependency heals.
            raise
        except WorkerExecutionError as error:
            heartbeat.require_owned()
            recovery = service._recovery_service.recover_session(
                claimed.lease.session_id,
                worker_lease=resumed.claimed.lease,
            )
            if recovery.session.status not in {SessionStatus.READY, SessionStatus.RUNNING}:
                raise
            recorder = service._projection_recorder_factory.build(
                session=recovery.session,
                workspace=recovery.workspace,
                lease=resumed.claimed.lease,
                ownership_check=heartbeat.require_owned,
            )
            progress = recover_execution_progress(service, claimed, heartbeat.require_owned)
            failed = finalize_worker_setup_failure(
                recorder=recorder,
                event_store=service._event_store,
                error=error,
                attempt_number=progress.head.state.attempt_number if progress else 1,
            )
            rebuild_task_index(service._task_index_store, claimed.lease.session_id)
            return failed


def persist_runtime_cleanup_failure(
    *,
    recorder: DurableHarnessEventRecorder,
    error: Exception,
    target: Literal["runtime", "tool_gateway"],
    created_at: datetime,
    attempt_number: int = 1,
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
            "attempt_number": attempt_number,
        },
        idempotency_key=(f"runtime-cleanup-failed:{target}:{recorder.session.current_sequence}"),
        created_at=created_at,
    )
    return recorder.append_event(event)


def destroy_runtime_with_evidence(
    runtime: Any,
    handle: Any,
    *,
    recorder: DurableHarnessEventRecorder,
    created_at: datetime,
    attempt_number: int,
) -> Exception | None:
    error = runtime_setup.destroy_runtime(runtime, handle)
    if error is not None:
        try:
            persist_runtime_cleanup_failure(
                recorder=recorder,
                error=error,
                target="runtime",
                created_at=created_at,
                attempt_number=attempt_number,
            )
        except Exception as evidence_error:
            error.add_note(f"cleanup evidence unavailable: {type(evidence_error).__name__}")
    return error


def raise_runtime_setup_failure(
    error: Exception,
    runtime: Any,
    handle: Any,
    *,
    recorder: DurableHarnessEventRecorder,
    stage: str,
    created_at: datetime,
    attempt_number: int,
) -> Never:
    if not isinstance(error, PluginAuthorityUnavailable):
        log_worker_failure("worker_setup_failed", stage, recorder.session.session_id, error)
    cleanup_error = destroy_runtime_with_evidence(
        runtime,
        handle,
        recorder=recorder,
        created_at=created_at,
        attempt_number=attempt_number,
    )
    if isinstance(error, PluginAuthorityUnavailable):
        raise WorkerPluginSetupUnavailable("accepted plugin authority is unavailable") from None
    if cleanup_error is not None:
        raise WorkerExecutionError(f"{error}; runtime cleanup failed: {cleanup_error}") from error
    if isinstance(error, RuntimeCapabilityError):
        raise RuntimeStartupError(str(error)) from error
    raise WorkerExecutionError(str(error)) from error
