"""Hosted Worker outer attempt coordination (Wave 5 Phase 1).

Coordinates Attempt 1 -> Attempt 2 under one Stable Task for retryable
failures and fails closed when the durable reconstruction is inconsistent
(W5-DSH-01/02). Durable attempt-event helpers live in ``attempt_events`` and
single-attempt execution in ``attempt_execution``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from agent_core.domain.agent_tasks import AgentTask
from agent_core.domain.attempt_policy import TaskAttemptPolicy
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventType, SessionEvent
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
    SQLiteArtifactPayloadStore,
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
    durable_events,
    materialize_attempt_start,
    reconstruct_current_attempt,
    record_attempt_outcome,
    should_retry_attempt,
    validate_attempt_reconstruction,
)
from zebra_agent_worker.attempt_execution import run_single_attempt
from zebra_agent_worker.claims import ClaimedSession, SessionClaimService
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
        claim_service: SessionClaimService,
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
        self._claim_service = claim_service
        self._event_store = event_store
        self._projection_store = projection_store
        self._workspace_store = workspace_store
        self._model_call_indexer = model_call_indexer
        self._tool_run_indexer = tool_run_indexer
        self._context_lifecycle_store = context_lifecycle_store
        self._provider_continuation_store = provider_continuation_store
        self._recovery_service = recovery_service
        self._settings = settings

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
        artifact_payload_store: SQLiteArtifactPayloadStore,
    ) -> CoordinatorResult:
        outcome: CoordinatorResult | None = None
        try:
            continuation, clarification = self._recover_continuations(session_events)
            claimed = self._mark_continuation_started(
                claimed,
                continuation=continuation,
                clarification=clarification,
                started_at=started_at,
            )
            recorder = DurableHarnessEventRecorder(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                event_store=self._event_store,
                projection_store=self._projection_store,
                workspace_store=self._workspace_store,
                model_call_indexer=self._model_call_indexer,
                tool_run_indexer=self._tool_run_indexer,
            )
            plan_revision = 1 + sum(
                1 for item in task_events if item.event.event_type is EventType.PLAN_UPDATED
            )
            outcome = self._coordinate(
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
                recorder=recorder,
                continuation=continuation,
                clarification=clarification,
                plan_revision=plan_revision,
                policy=policy,
                artifact_payload_store=artifact_payload_store,
            )
        finally:
            cleanup_error = close_tool_gateway(tool_gateway)
        assert outcome is not None
        if cleanup_error is not None:
            outcome = replace(
                outcome,
                attempt_result=runtime_cleanup_failure_result(
                    cleanup_error, outcome.attempt_result
                ),
            )
        return outcome

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
        recorder: DurableHarnessEventRecorder,
        continuation: ApprovedContinuation | None,
        clarification: ClarificationContinuation | None,
        plan_revision: int,
        policy: TaskAttemptPolicy,
        artifact_payload_store: SQLiteArtifactPayloadStore,
    ) -> CoordinatorResult:
        try:
            current = reconstruct_current_attempt(session_events, policy)
            if (continuation is not None or clarification is not None) and current != 1:
                raise AttemptReconstructionError(
                    "continuation requires the first attempt to be in flight"
                )
            if current == 0:
                return self._complete_terminal_after_outcome(
                    recorder=recorder,
                    session_events=session_events,
                    started_at=started_at,
                    claimed=claimed,
                )
            attempt = attempt_for(current, started_at=started_at)
            durable = durable_events(session_events, recorder)
            materialize_attempt_start(recorder, attempt, durable, started_at=started_at)
            validate_attempt_reconstruction(durable, attempt)
        except AttemptReconstructionError as exc:
            return self._fail_closed(
                recorder=recorder,
                session_events=session_events,
                started_at=started_at,
                error=str(exc),
                claimed=claimed,
            )

        attempt_result: HarnessAttemptResult | None = None
        suspension_snapshot: RuntimeSnapshot | None = None
        while True:
            durable = durable_events(session_events, recorder)
            materialize_attempt_start(recorder, attempt, durable, started_at=attempt.started_at)
            validate_attempt_reconstruction(durable, attempt)
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
                plan_revision=plan_revision,
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
                # External durable control terminalized the Task mid-attempt
                # (e.g. cancel); stop without an attempt outcome record.
                break
            retry_scheduled = should_retry_attempt(policy, attempt_result, attempt.number)
            if attempt_result.outcome in {
                HarnessAttemptOutcome.COMPLETED,
                HarnessAttemptOutcome.FAILED,
            }:
                # Paused states (waiting approval/input, suspended) are not
                # attempt outcomes: continuation/suspension recovery resumes
                # the same attempt from the durable stream.
                record_attempt_outcome(
                    recorder,
                    attempt=attempt,
                    result=attempt_result,
                    ended_at=datetime.now(UTC),
                    retry_scheduled=retry_scheduled,
                )
            if not retry_scheduled:
                break
            attempt = attempt_for(attempt.number + 1, started_at=datetime.now(UTC))
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
    ) -> ClaimedSession:
        if continuation is not None:
            return mark_approved_continuation_started(
                claimed,
                event_store=self._event_store,
                recovery_service=self._recovery_service,
                tool_name=continuation.tool_call.name,
                tool_call_id=str(continuation.tool_call.tool_call_id),
                started_at=started_at,
            )
        if clarification is not None:
            return mark_clarification_continuation_started(
                claimed,
                event_store=self._event_store,
                recovery_service=self._recovery_service,
                clarification_id=str(clarification.tool_call.tool_call_id),
                started_at=started_at,
            )
        return claimed

    def _complete_terminal_after_outcome(
        self,
        *,
        recorder: DurableHarnessEventRecorder,
        session_events: list[SessionEvent],
        started_at: datetime,
        claimed: ClaimedSession,
    ) -> CoordinatorResult:
        """Crash between a non-retriable/exhausted outcome and Task terminal:
        synthesize the missing terminal without dispatching anything."""
        outcomes = [
            event
            for event in session_events
            if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
        ]
        last = outcomes[-1]
        attempt = attempt_for(int(last.payload["attempt_sequence"]), started_at=started_at)
        attempt_result = HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="attempt policy exhausted before terminal commit",
            metadata={
                "stop_reason": last.payload["terminal_reason"],
                "attempt_id": last.payload["attempt_id"],
            },
        )
        return CoordinatorResult(
            attempt_result=attempt_result,
            suspension_snapshot=None,
            recorder=recorder,
            attempt=attempt,
            claimed=claimed,
        )

    def _fail_closed(
        self,
        *,
        recorder: DurableHarnessEventRecorder,
        session_events: list[SessionEvent],
        started_at: datetime,
        error: str,
        claimed: ClaimedSession,
    ) -> CoordinatorResult:
        """Inconsistent durable reconstruction: record the attempt outcome and
        terminalize without ever calling the model gateway."""
        starts = [
            event
            for event in session_events
            if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
        ]
        sequence = (
            int(starts[-1].payload.get("attempt_sequence") or starts[-1].payload["attempt_number"])
            if starts
            else 1
        )
        attempt = attempt_for(sequence, started_at=started_at)
        durable = durable_events(session_events, recorder)
        materialize_attempt_start(recorder, attempt, durable, started_at=started_at)
        record_attempt_outcome(
            recorder,
            attempt=attempt,
            result=HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="attempt reconstruction failed closed",
                metadata={"stop_reason": "attempt_reconstruction_invalid"},
            ),
            ended_at=datetime.now(UTC),
            retry_scheduled=False,
        )
        return CoordinatorResult(
            attempt_result=HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="attempt reconstruction failed closed",
                metadata={
                    "stop_reason": "attempt_reconstruction_invalid",
                    "error_message": error,
                },
            ),
            suspension_snapshot=None,
            recorder=recorder,
            attempt=attempt,
            claimed=claimed,
        )
