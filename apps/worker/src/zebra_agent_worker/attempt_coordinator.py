"""Hosted Worker outer attempt coordination (Wave 5 Phase 1 + Gate 1).

Coordinates Attempt 1 -> Attempt 2 under one Stable Task for retryable
failures, reconstructs attempt state from the ordered Stable Task stream
(epoch-scoped), persists stable start/outcome coordinates, and fails closed
when the durable reconstruction is inconsistent (W5-DSH-01/02).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_core.domain.agent_tasks import AgentTask, ExecutionSegment
from agent_core.domain.attempt_policy import TaskAttemptPolicy
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import SessionStatus
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
)
from agent_core.ports.agent_tasks import TaskEvent
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort, RuntimeSnapshot
from agent_runtime import FinosJournalProvider
from agent_security import NetworkProfile
from agent_storage import (
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteProviderContinuationStore,
    SQLiteWorkspaceProjectionStore,
)
from agent_tools import EffectGuardedToolGateway
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.approved_continuation import (
    ApprovedContinuation,
    ApprovedContinuationError,
    recover_approved_continuation,
)
from zebra_agent_worker.attempt_events import (
    AttemptReconstructionError,
    attempt_for,
    derive_epoch_coordinates,
    derive_plan_revision,
    durable_events,
    durable_usage,
    epoch_scoped_events,
    materialize_attempt_start,
    reconstruct_current_attempt,
    record_attempt_outcome,
    remaining_budget,
    should_retry_attempt,
    usage_int,
    validate_attempt_reconstruction,
)
from zebra_agent_worker.attempt_execution import run_single_attempt
from zebra_agent_worker.attempt_recovery import (
    _budget_blocked_result,
    complete_terminal_after_outcome,
    fail_closed,
)
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.clarification_continuation import (
    ClarificationContinuation,
    ClarificationContinuationError,
    recover_clarification_continuation,
)
from zebra_agent_worker.continuation_lifecycle import (
    mark_approved_continuation_started,
    mark_clarification_continuation_started,
)
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.runtime_authority import (
    close_tool_gateway,
    runtime_cleanup_failure_result,
)
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.tool_run_index import ToolRunIndexer


@dataclass(frozen=True)
class CoordinatorResult:
    attempt_result: HarnessAttemptResult
    suspension_snapshot: RuntimeSnapshot | None
    recorder: DurableHarnessEventRecorder
    attempt: HarnessAttempt
    claimed: ClaimedSession


class HostedAttemptCoordinator:
    def __init__(
        self,
        *,
        event_store: SQLiteEventStore,
        projection_store: SQLiteProjectionStore,
        workspace_store: SQLiteWorkspaceProjectionStore,
        model_call_indexer: ModelCallIndexer,
        tool_run_indexer: ToolRunIndexer,
        context_lifecycle_store: SQLiteContextLifecycleStore,
        provider_continuation_store: SQLiteProviderContinuationStore,
        recovery_service: SessionRecoveryService,
        settings: ZebraAgentSettings,
    ) -> None:
        self._event_store = event_store
        self._projection_store = projection_store
        self._workspace_store = workspace_store
        self._model_call_indexer = model_call_indexer
        self._tool_run_indexer = tool_run_indexer
        self._context_lifecycle_store = context_lifecycle_store
        self._provider_continuation_store = provider_continuation_store
        self._recovery_service = recovery_service
        self._settings = settings
        self._gateway_closed = False

    def run(
        self,
        *,
        session_id: SessionId,
        started_at: datetime,
        task: RecoveredTask,
        task_record: AgentTask,
        claimed: ClaimedSession,
        base_context: HarnessContext,
        model_gateway: ModelGatewayPort,
        tool_gateway: EffectGuardedToolGateway,
        runtime: RuntimePort,
        runtime_handle: RuntimeHandle,
        finos_journal_provider: FinosJournalProvider | None,
        trusted_local: bool,
        effective_network_profile: NetworkProfile,
        provider_continuation: ProviderContinuationRef | None,
        session_events: list[SessionEvent],
        task_events: tuple[TaskEvent, ...],
        policy: TaskAttemptPolicy,
        segments: tuple[ExecutionSegment, ...],
    ) -> CoordinatorResult:
        self._gateway_closed = False
        self._segments = segments
        try:
            continuation, clarification = self._recover_continuations(session_events)
            recorder = DurableHarnessEventRecorder(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                event_store=self._event_store,
                projection_store=self._projection_store,
                workspace_store=self._workspace_store,
                model_call_indexer=self._model_call_indexer,
                tool_run_indexer=self._tool_run_indexer,
            )
            return self._coordinate(
                session_id=session_id,
                started_at=started_at,
                task=task,
                task_record=task_record,
                claimed=claimed,
                base_context=base_context,
                model_gateway=model_gateway,
                tool_gateway=tool_gateway,
                runtime=runtime,
                runtime_handle=runtime_handle,
                finos_journal_provider=finos_journal_provider,
                trusted_local=trusted_local,
                effective_network_profile=effective_network_profile,
                provider_continuation=provider_continuation,
                session_events=session_events,
                task_events=task_events,
                recorder=recorder,
                continuation=continuation,
                clarification=clarification,
                policy=policy,
                segments=segments,
            )
        finally:
            if not self._gateway_closed:
                cleanup_error = close_tool_gateway(tool_gateway)
                if cleanup_error is not None:
                    active_exc = sys.exc_info()[1]
                    if active_exc is not None:
                        raise ValueError(
                            f"{active_exc}; runtime cleanup failed: {cleanup_error}"
                        ) from active_exc

    def _coordinate(
        self,
        *,
        session_id: SessionId,
        started_at: datetime,
        task: RecoveredTask,
        task_record: AgentTask,
        claimed: ClaimedSession,
        base_context: HarnessContext,
        model_gateway: ModelGatewayPort,
        tool_gateway: EffectGuardedToolGateway,
        runtime: RuntimePort,
        runtime_handle: RuntimeHandle,
        finos_journal_provider: FinosJournalProvider | None,
        trusted_local: bool,
        effective_network_profile: NetworkProfile,
        provider_continuation: ProviderContinuationRef | None,
        session_events: list[SessionEvent],
        task_events: tuple[TaskEvent, ...],
        recorder: DurableHarnessEventRecorder,
        continuation: ApprovedContinuation | None,
        clarification: ClarificationContinuation | None,
        policy: TaskAttemptPolicy,
        segments: tuple[ExecutionSegment, ...],
    ) -> CoordinatorResult:
        scoped = epoch_scoped_events(list(task_events), segments)
        epoch_sequence, turn_id = derive_epoch_coordinates(list(task_events), segments)
        try:
            current = reconstruct_current_attempt(scoped, policy)
            # Validate the complete active-epoch chain (including in-flight
            # model-step correlation) before dispatch AND terminal recovery.
            validate_attempt_reconstruction(
                scoped,
                attempt_for(max(current, 1), started_at=started_at),
                max_attempts=policy.max_attempts,
                epoch_sequence=epoch_sequence,
                turn_id=turn_id,
            )
            if current == 0:
                terminal_result, terminal_attempt = complete_terminal_after_outcome(
                    recorder=recorder,
                    scoped_events=scoped,
                    started_at=started_at,
                    claimed=claimed,
                    tool_gateway=tool_gateway,
                    close_gateway=self._close_gateway,
                )
                return CoordinatorResult(
                    attempt_result=terminal_result,
                    suspension_snapshot=None,
                    recorder=recorder,
                    attempt=terminal_attempt,
                    claimed=claimed,
                )
            attempt = attempt_for(current, started_at=started_at)
        except AttemptReconstructionError as exc:
            closed_result, closed_attempt = fail_closed(
                recorder=recorder,
                scoped_events=scoped,
                started_at=started_at,
                error=str(exc),
                tool_gateway=tool_gateway,
                close_gateway=self._close_gateway,
                turn_id=turn_id,
                epoch_sequence=epoch_sequence,
            )
            return CoordinatorResult(
                attempt_result=closed_result,
                suspension_snapshot=None,
                recorder=recorder,
                attempt=closed_attempt,
                claimed=claimed,
            )
        if continuation is not None or clarification is not None:
            claimed = self._mark_continuation_started(
                claimed,
                continuation=continuation,
                clarification=clarification,
                started_at=started_at,
                attempt=attempt if policy.max_attempts > 1 else None,
            )

        def plan_revision_provider() -> int:
            return derive_plan_revision([*scoped, *recorder.events])

        attempt_result: HarnessAttemptResult | None = None
        suspension_snapshot: RuntimeSnapshot | None = None
        model_calls_used, tool_calls_used = durable_usage([*scoped, *recorder.events])
        while True:
            budget_blocked = _budget_blocked_result(
                attempt,
                model_calls_used,
                tool_calls_used,
                task.max_model_calls,
                task.max_tool_calls,
            )
            if budget_blocked is not None:
                # Frozen Task budget is spent: terminalize deterministically
                # with zero provider calls (never an endless suspend cycle).
                attempt_result = budget_blocked
                suspension_snapshot = None
            else:
                try:
                    durable = durable_events(scoped, recorder)
                    # Validate the complete existing chain BEFORE materializing
                    # any missing start so a corrupt chain is never extended.
                    validate_attempt_reconstruction(
                        durable,
                        attempt,
                        max_attempts=policy.max_attempts,
                        epoch_sequence=epoch_sequence,
                        turn_id=turn_id,
                    )
                    materialize_attempt_start(
                        recorder,
                        attempt,
                        durable,
                        started_at=attempt.started_at,
                        turn_id=turn_id,
                        epoch_sequence=epoch_sequence,
                    )
                except AttemptReconstructionError as exc:
                    attempt_result, attempt = fail_closed(
                        recorder=recorder,
                        scoped_events=scoped,
                        started_at=started_at,
                        error=str(exc),
                        tool_gateway=tool_gateway,
                        close_gateway=self._close_gateway,
                        turn_id=turn_id,
                        epoch_sequence=epoch_sequence,
                    )
                    return CoordinatorResult(
                        attempt_result=attempt_result,
                        suspension_snapshot=None,
                        recorder=recorder,
                        attempt=attempt,
                        claimed=claimed,
                    )
                attempt_result, suspension_snapshot = run_single_attempt(
                    session_id=session_id,
                    attempt=attempt,
                    recorder=recorder,
                    task=task,
                    task_record=task_record,
                    base_context=base_context,
                    model_gateway=model_gateway,
                    tool_gateway=tool_gateway,
                    runtime=runtime,
                    runtime_handle=runtime_handle,
                    finos_journal_provider=finos_journal_provider,
                    trusted_local=trusted_local,
                    effective_network_profile=effective_network_profile,
                    provider_continuation=provider_continuation,
                    continuation=continuation,
                    clarification=clarification,
                    plan_revision_provider=plan_revision_provider,
                    remaining_model_calls=remaining_budget(task.max_model_calls, model_calls_used),
                    remaining_tool_calls=remaining_budget(task.max_tool_calls, tool_calls_used),
                    scoped_events=scoped,
                    segments=segments,
                    task_events=task_events,
                    guarded=policy.max_attempts > 1,
                    event_store=self._event_store,
                    context_lifecycle_store=self._context_lifecycle_store,
                    provider_continuation_store=self._provider_continuation_store,
                    settings=self._settings,
                )
            continuation = None
            clarification = None
            if recorder.session.status in {
                SessionStatus.CANCELLED,
                SessionStatus.COMPLETED,
                SessionStatus.FAILED,
            }:
                break
            model_calls_used += usage_int(attempt_result.metadata, "model_calls_used", 1)
            tool_calls_used += usage_int(attempt_result.metadata, "tool_calls_executed", 0)
            retry_scheduled = should_retry_attempt(
                policy,
                attempt_result,
                attempt.number,
                model_calls_used=model_calls_used,
                tool_calls_used=tool_calls_used,
                max_model_calls=task.max_model_calls,
                max_tool_calls=task.max_tool_calls,
            )
            if retry_scheduled:
                record_attempt_outcome(
                    recorder,
                    attempt=attempt,
                    result=attempt_result,
                    ended_at=datetime.now(UTC),
                    retry_scheduled=True,
                    turn_id=turn_id,
                    epoch_sequence=epoch_sequence,
                )
                attempt = attempt_for(attempt.number + 1, started_at=datetime.now(UTC))
                continue
            cleanup_error = self._close_gateway(tool_gateway)
            if cleanup_error is not None:
                attempt_result = runtime_cleanup_failure_result(cleanup_error, attempt_result)
            paused = attempt_result.outcome in {
                HarnessAttemptOutcome.WAITING_APPROVAL,
                HarnessAttemptOutcome.WAITING_INPUT,
                HarnessAttemptOutcome.SUSPENDED,
            }
            if not paused or cleanup_error is not None:
                record_attempt_outcome(
                    recorder,
                    attempt=attempt,
                    result=attempt_result,
                    ended_at=datetime.now(UTC),
                    retry_scheduled=False,
                    turn_id=turn_id,
                    epoch_sequence=epoch_sequence,
                )
            break
        assert attempt_result is not None
        return CoordinatorResult(
            attempt_result=attempt_result,
            suspension_snapshot=suspension_snapshot,
            recorder=recorder,
            attempt=attempt,
            claimed=claimed,
        )

    def _recover_continuations(
        self,
        session_events: list[SessionEvent],
    ) -> tuple[ApprovedContinuation | None, ClarificationContinuation | None]:
        try:
            continuation = recover_approved_continuation(session_events)
            clarification = recover_clarification_continuation(session_events)
            if continuation is not None and clarification is not None:
                raise ValueError("session has multiple active continuations")
            return continuation, clarification
        except (
            ApprovedContinuationError,
            ClarificationContinuationError,
            ValueError,
        ) as exc:
            raise ValueError(str(exc)) from exc

    def _mark_continuation_started(
        self,
        claimed: ClaimedSession,
        *,
        continuation: ApprovedContinuation | None,
        clarification: ClarificationContinuation | None,
        started_at: datetime,
        attempt: HarnessAttempt | None,
    ) -> ClaimedSession:
        if continuation is not None:
            return mark_approved_continuation_started(
                claimed,
                event_store=self._event_store,
                recovery_service=self._recovery_service,
                tool_name=continuation.tool_call.name,
                tool_call_id=str(continuation.tool_call.tool_call_id),
                started_at=started_at,
                attempt=attempt,
            )
        if clarification is not None:
            return mark_clarification_continuation_started(
                claimed,
                event_store=self._event_store,
                recovery_service=self._recovery_service,
                clarification_id=str(clarification.tool_call.tool_call_id),
                started_at=started_at,
                attempt=attempt,
            )
        return claimed

    def _close_gateway(self, tool_gateway: EffectGuardedToolGateway) -> Exception | None:
        self._gateway_closed = True
        return close_tool_gateway(tool_gateway)
