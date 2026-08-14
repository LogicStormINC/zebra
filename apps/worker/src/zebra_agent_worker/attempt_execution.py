"""Single-attempt execution for the Hosted Worker (Wave 5 Phase 1)."""

from __future__ import annotations

from dataclasses import replace

from agent_context import LocalContextCompiler
from agent_core.domain.agent_tasks import AgentTask
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
    HarnessModelStep,
    SingleAttemptOrchestrator,
)
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort, RuntimeSnapshot
from agent_runtime import FinosJournalProvider
from agent_security import LocalPolicyEngine, NetworkProfile
from agent_storage import (
    SQLiteContextLifecycleStore,
    SQLiteEventStore,
    SQLiteProviderContinuationStore,
)
from agent_tools import EffectGuardedToolGateway
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.attempt_lifecycle import execute_attempt
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.context_lifecycle import persist_context_compaction
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.finos_journal_provider import (
    allows_finos_account_changes_proposal,
)
from zebra_agent_worker.task_preapproval import build_policy_engine
from zebra_agent_worker.task_recovery import RecoveredTask


def run_single_attempt(
    *,
    session_id: SessionId,
    attempt: HarnessAttempt,
    recorder: DurableHarnessEventRecorder,
    task: RecoveredTask,
    task_record: AgentTask,
    base_context: HarnessContext,
    model_gateway: ModelGatewayPort,
    tool_gateway: EffectGuardedToolGateway,
    runtime: RuntimePort,
    runtime_handle: RuntimeHandle,
    finos_journal_provider: FinosJournalProvider | None,
    trusted_local: bool,
    effective_network_profile: NetworkProfile,
    provider_continuation: ProviderContinuationRef | None,
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
    plan_revision: int,
    event_store: SQLiteEventStore,
    context_lifecycle_store: SQLiteContextLifecycleStore,
    provider_continuation_store: SQLiteProviderContinuationStore,
    settings: ZebraAgentSettings,
) -> tuple[HarnessAttemptResult, RuntimeSnapshot | None]:
    """Run one attempt and return its result plus the suspension snapshot."""
    context = replace(
        base_context,
        attempt=attempt,
        session=recorder.session.model_copy(update={"task_plan": task_record.task_plan}),
    )
    context_compiler = LocalContextCompiler()

    def persist_event(draft: HarnessEventDraft) -> None:
        if draft.event_type is EventType.CONTEXT_COMPACTED:
            persist_context_compaction(
                draft,
                recorder=recorder,
                event_store=event_store,
                lifecycle_store=context_lifecycle_store,
            )
            return
        if draft.event_type in {
            EventType.MODEL_REQUEST_STARTED,
            EventType.MODEL_RESPONSE_RECEIVED,
        }:
            payload = {
                **draft.payload,
                "attempt_id": attempt.attempt_id,
                "stable_task_id": str(task_record.task_id),
            }
            if draft.event_type is EventType.MODEL_REQUEST_STARTED:
                payload.update(
                    {
                        "turn_id": str(session_id),
                        "step_id": draft.payload.get("model_call_id"),
                        "goal_revision": 1,
                        "plan_revision": plan_revision,
                    }
                )
            recorder.append_draft(replace(draft, payload=payload))
            return
        recorder.append_draft(draft)

    def persist_continuation(
        reference: ProviderContinuationRef,
        payload: bytes | None,
        maximum_ttl_seconds: int | None,
    ) -> str | None:
        if payload is None:
            return None
        artifact = provider_continuation_store.store(
            tenant_id="local",
            session_id=str(session_id),
            reference=reference,
            opaque_payload=payload,
            maximum_ttl_seconds=maximum_ttl_seconds,
        )
        return artifact.artifact_id

    model_step = HarnessModelStep(
        context_compiler=context_compiler,
        available_tools=tool_gateway.model_tools,
        conversation_compactor=context_compiler,
        event_sink=persist_event,
        continuation_sink=persist_continuation,
        provider_continuation=provider_continuation,
        attempt_number=attempt.number,
    )
    policy_engine = build_policy_engine(
        LocalPolicyEngine,
        task,
        effective_network_profile,
        settings,
        tool_gateway.effective_mcp_tools,
        trusted_local,
        allows_finos_account_changes_proposal(finos_journal_provider),
    )
    orchestrator = SingleAttemptOrchestrator(
        model_gateway,
        policy_engine,
        tool_gateway,
        model_step=model_step,
        synthesize_tool_results=True,
        parallel_safe_tools=tool_gateway.parallel_safe_tools,
        parallel_batch_limits=tool_gateway.parallel_batch_limits,
        max_parallel_tool_calls=3,
        tool_call_resolver=tool_gateway.resolve_model_tool_calls,
        validator_tool_names=tool_gateway.validator_tools,
        event_sink=persist_event,
    )
    return execute_attempt(
        orchestrator,
        context,
        continuation=continuation,
        clarification=clarification,
        runtime=runtime,
        runtime_handle=runtime_handle,
    )
