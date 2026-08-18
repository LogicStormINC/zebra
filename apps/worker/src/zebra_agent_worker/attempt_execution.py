"""Single-attempt execution for the Hosted Worker (Wave 5 Phase 1)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from agent_context import LocalContextCompiler
from agent_core.domain.agent_tasks import AgentTask, ExecutionSegment
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelInvocationPolicy, ModelToolChoice, ModelToolDefinition
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventDraft,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)
from agent_core.harness.completion_evidence import persisted_completion_evidence_events
from agent_core.harness.context_recovery import (
    append_final_answer_instruction,
    append_validator_correction_instruction,
    prepare_bounded_conversation,
)
from agent_core.harness.orchestrator import ACTIVE_PROJECTION_FOLLOW_UP_GUIDANCE
from agent_core.harness.reconstruction import (
    NO_RESOURCE_MANIFEST_DIGEST,
    RequestReconstruction,
    invocation_policy_digest,
    media_inputs_digest,
    model_config_digest,
    system_prompt_digest,
)
from agent_core.harness.required_tool_request import selected_model_tools
from agent_core.ports.agent_tasks import TaskEvent
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
from zebra_agent_config import ZebraAgentSettings, settings_for_model

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.attempt_events import (
    derive_turn_id,
    durable_events,
    mirror_attempt_messages,
)
from zebra_agent_worker.attempt_lifecycle import execute_attempt
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.context_lifecycle import persist_context_compaction
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.finos_journal_provider import (
    allows_finos_account_changes_proposal,
)
from zebra_agent_worker.runtime_guidance import (
    _continuation_boundary_index,
    rebuilt_runtime_guidance,
)
from zebra_agent_worker.task_preapproval import build_policy_engine
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.terminal_synthesis import terminal_synthesis_pending


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
    plan_revision_provider: Callable[[], int],
    remaining_model_calls: int | None,
    remaining_tool_calls: int | None,
    scoped_events: list[SessionEvent],
    segments: tuple[ExecutionSegment, ...],
    task_events: tuple[TaskEvent, ...],
    guarded: bool,
    event_store: SQLiteEventStore,
    context_lifecycle_store: SQLiteContextLifecycleStore,
    provider_continuation_store: SQLiteProviderContinuationStore,
    settings: ZebraAgentSettings,
) -> tuple[HarnessAttemptResult, RuntimeSnapshot | None]:
    """Run one attempt and return its result plus the suspension snapshot."""
    attempt_task = replace(
        base_context.task,
        max_model_calls=remaining_model_calls,
        max_tool_calls=remaining_tool_calls,
        task_plan=recorder.session.task_plan,
    )
    reconstruction = (
        _build_reconstruction(
            attempt=attempt,
            attempt_task=attempt_task,
            task_record=task_record,
            session_id=session_id,
            scoped_events=scoped_events,
            segments=segments,
            task_events=task_events,
            recorder=recorder,
            model_gateway=model_gateway,
            tool_gateway=tool_gateway,
            plan_revision=plan_revision_provider(),
            settings=settings,
            continuation=continuation,
            clarification=clarification,
        )
        if guarded
        else None
    )
    context = replace(
        base_context,
        task=attempt_task,
        attempt=attempt,
        session=recorder.session,
        completion_evidence_events=(
            base_context.completion_evidence_events
            + persisted_completion_evidence_events(recorder.events)
        ),
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
            if draft.event_type is EventType.MODEL_REQUEST_STARTED:
                payload = {
                    **draft.payload,
                    "plan_revision": plan_revision_provider(),
                }
            else:
                payload = {
                    **draft.payload,
                    "attempt_id": attempt.attempt_id,
                    "stable_task_id": str(task_record.task_id),
                }
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
        reconstruction=reconstruction,
        plan_revision_provider=plan_revision_provider,
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


def _build_reconstruction(
    *,
    attempt: HarnessAttempt,
    attempt_task: HarnessTask,
    task_record: AgentTask,
    session_id: SessionId,
    scoped_events: list[SessionEvent],
    segments: tuple[ExecutionSegment, ...],
    task_events: tuple[TaskEvent, ...],
    recorder: DurableHarnessEventRecorder,
    model_gateway: ModelGatewayPort,
    tool_gateway: EffectGuardedToolGateway,
    plan_revision: int,
    settings: ZebraAgentSettings,
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
) -> RequestReconstruction:
    compiler = LocalContextCompiler()
    probe = HarnessModelStep(
        context_compiler=compiler,
        available_tools=tool_gateway.model_tools,
        conversation_compactor=compiler,
    )
    initial = probe.build_initial_messages(
        attempt_task,
        created_at=attempt.started_at,
        model_gateway=model_gateway,
    )
    follow_up_guidance_needed = any(
        evidence.kind == "session_handoff"
        and (evidence.metadata or {}).get("handoff_source") == "active_projection"
        and (evidence.metadata or {}).get("handoff_reason") == "internal_terminal_follow_up"
        for evidence in attempt_task.runtime_evidence
    )
    continuation_conversation = _continuation_conversation(
        continuation, clarification, created_at=attempt.started_at
    )
    has_continuation = bool(continuation_conversation)
    base_full_messages = (
        continuation_conversation if has_continuation else list(initial)
    )
    base_evidence_events = persisted_completion_evidence_events(
        item.event for item in task_events
    )

    def durable_tail() -> list[SessionEvent]:
        """Events the current dispatch is verified against.

        For a continuation, everything at or before the last snapshot
        boundary is already materialized in the recovered conversation, so
        only the durable tail after that boundary is replayed/rebuilt.
        Without a boundary the guard still fails closed (full replay)."""
        full = durable_events(scoped_events, recorder)
        if not has_continuation:
            return full
        boundary_index = _continuation_boundary_index(full)
        if boundary_index is None:
            return full
        return full[boundary_index + 1 :]

    def runtime_guidance() -> tuple[SessionMessage, ...]:
        # Full request-envelope equality: the exact runtime guidance actually
        # sent to the provider is independently rebuilt from durable
        # evidence/plan state via the same helpers the harness uses.
        return rebuilt_runtime_guidance(
            durable_tail(),
            attempt=attempt,
            task=attempt_task,
            session=recorder.session,
            completion_evidence_events=(
                base_evidence_events
                + persisted_completion_evidence_events(recorder.events)
            ),
            created_at=attempt.started_at,
            prior_messages=continuation_conversation if has_continuation else (),
            base_evidence_events=base_evidence_events,
        )

    def step_envelope(
        step_kind: str,
        allow_tools: bool,
        required_tool_names: tuple[str, ...],
    ) -> tuple[str, tuple[ModelToolDefinition, ...], str]:
        expected_invocation = invocation_policy_digest(
            ModelInvocationPolicy(tool_choice=ModelToolChoice.REQUIRED)
            if required_tool_names
            else None
        )
        if has_continuation:
            # Continuation dispatches use the durable recovered conversation;
            # its system messages (stable prompt + runtime guidance) are the
            # independently derived expected envelope, plus any runtime
            # guidance appended by the resumed run (e.g. a typed evidence
            # correction observation), through the same durable replay.
            expected_tools = selected_model_tools(
                tool_gateway.model_tools,
                allow_tools=allow_tools,
                required_names=required_tool_names,
            )
            return (
                system_prompt_digest(rebuilt_system_messages()),
                expected_tools,
                expected_invocation,
            )
        system_messages = rebuilt_system_messages()
        if follow_up_guidance_needed:
            system_messages.append(
                SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.SYSTEM,
                    content=ACTIVE_PROJECTION_FOLLOW_UP_GUIDANCE,
                    created_at=attempt.started_at,
                )
            )
        if step_kind == "terminal_synthesis":
            append_final_answer_instruction(system_messages, created_at=attempt.started_at)
        elif step_kind == "validator_correction":
            append_validator_correction_instruction(system_messages, created_at=attempt.started_at)
        expected_tools = selected_model_tools(
            tool_gateway.model_tools,
            allow_tools=allow_tools,
            required_names=required_tool_names,
        )
        return (
            system_prompt_digest(system_messages),
            expected_tools,
            expected_invocation,
        )

    def rebuilt_messages() -> list[SessionMessage]:
        """Full expected request messages (systems + conversation) derived
        only from durable state: the fresh/recovered base, the rebuilt
        runtime guidance, the mirrored durable tail, the sanctioned
        compaction transform at each durable boundary, and the
        terminal-synthesis final-answer instruction. The conversation digest
        ignores system messages; the system digest uses exactly the rebuilt
        system messages so a durable compaction is reproduced identically."""
        full_current = durable_events(scoped_events, recorder)
        current = durable_tail()
        # Deterministic durable replay: rebuild the conversation the harness
        # derives from the durable stream, re-applying the sanctioned
        # compaction transform through the existing bounded-conversation
        # builder at each durable compaction boundary.
        replay: list[SessionMessage] = list(base_full_messages)
        replay.extend(runtime_guidance())
        segment: list[SessionEvent] = []
        for event in current:
            if event.event_type in {
                EventType.CONTEXT_COMPACTED,
                EventType.CONTEXT_CAPSULE_CREATED,
            }:
                replay.extend(
                    mirror_attempt_messages(
                        segment,
                        attempt_number=attempt.number,
                        created_at=attempt.started_at,
                        provider_events=full_current,
                    )
                )
                segment = []
                prepare_bounded_conversation(
                    replay,
                    model_gateway,
                    allow_tools=True,
                    available_tools=tool_gateway.model_tools,
                    conversation_compactor=compiler,
                    conversation_token_budget=attempt_task.context_token_budget,
                    compaction_hook=None,
                    user_goal=attempt_task.stable_goal,
                    created_at=attempt.started_at,
                )
            else:
                segment.append(event)
        replay.extend(
            mirror_attempt_messages(
                segment,
                attempt_number=attempt.number,
                created_at=attempt.started_at,
                provider_events=full_current,
            )
        )
        if terminal_synthesis_pending(
            current,
            attempt.number,
            task=attempt_task,
            session=recorder.session,
            created_at=attempt.started_at,
            full_stream=full_current,
        ):
            # A durable provisional-final response (tool_loop stage, no tool
            # execution following) schedules the terminal-synthesis dispatch,
            # whose actual conversation carries the fixed final-answer
            # instruction appended by prepare_terminal_conversation.
            append_final_answer_instruction(replay, created_at=attempt.started_at)
        return replay

    def rebuilt_system_messages() -> list[SessionMessage]:
        return [
            message
            for message in rebuilt_messages()
            if message.role is MessageRole.SYSTEM
        ]

    rebuild = rebuilt_messages

    model_settings = settings_for_model(settings, attempt_task.model_id).model
    config_basis = f"{model_settings.provider}:{model_settings.model}"
    return RequestReconstruction(
        stable_task_id=str(task_record.task_id),
        attempt_id=attempt.attempt_id or f"attempt-{attempt.number}",
        turn_id=derive_turn_id(list(task_events), segments),
        goal_revision=1,
        plan_revision=plan_revision,
        messages_rebuild=rebuild,
        step_envelope=step_envelope,
        system_prompt_digest=None,
        tool_schema_digest=None,
        media_digest=media_inputs_digest(attempt_task.media_inputs),
        model_config_digest=model_config_digest(config_basis),
        resource_manifest_digest=NO_RESOURCE_MANIFEST_DIGEST,
    )


def _continuation_conversation(
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
    *,
    created_at: datetime,
) -> tuple[SessionMessage, ...]:
    if continuation is not None:
        return continuation.conversation
    if clarification is not None:
        from agent_core.harness.clarification_step import clarification_tool_result

        tool_message = SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.TOOL,
            content=clarification_tool_result(
                clarification.tool_call.tool_call_id,
                str(clarification.tool_call.tool_call_id),
                clarification.response,
            ).output,
            created_at=created_at,
            tool_call_id=str(clarification.tool_call.tool_call_id),
            metadata={"tool_result_status": "succeeded"},
        )
        return (*clarification.conversation, tool_message)
    return ()
