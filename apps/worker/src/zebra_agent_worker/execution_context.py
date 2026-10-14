"""Build the immutable Harness task view from recovered Worker state."""

from collections.abc import Callable
from time import monotonic
from typing import Any

from agent_context import (
    context_inputs_from_delegated_snapshot,
    context_inputs_from_materialization,
)
from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessModelStep, HarnessTask, SingleAttemptOrchestrator
from agent_core.harness import public_output_lifecycle as output_lifecycle
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_expression import PublicExpression
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.ports import MemoryReadPort, UserPersonalizationStorePort
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput
from agent_storage import list_confirmed_repo_memories
from agent_tools import FencedEffectToolGateway

import zebra_agent_worker.provider_continuation_execution as provider_runtime
from zebra_agent_worker.progress_recovery import WorkerProgressRecovery
from zebra_agent_worker.public_output_runtime import publication_scope
from zebra_agent_worker.task_recovery import RecoveredTask
from zebra_agent_worker.transient_output_runtime import TransientDeltaSink

CLOUD_CONTEXT_TOKEN_BUDGET = 2_048
CLOUD_CONVERSATION_TOKEN_BUDGET: int | None = None
HOST_EMBEDDED_AGENT_IDENTITY_DIRECTIVE = (
    "You are the product assistant embedded by the invoking Host application. Follow the "
    "Host-provided product role and identity in the task context. Never identify yourself as "
    "the underlying agent runtime, an engineering assistant, or a coding assistant unless the "
    "Host explicitly defines that product role. When the current request needs external facts "
    "or actions, proactively use the relevant available Host tools. Ask for required configuration "
    "only when missing. Never claim a real external operation succeeded without a successful "
    "tool result; quoting or transforming supplied text does not itself request an operation. "
    "Reconcile conflicting "
    "evidence, verify mutations with a fresh read when a read tool exists, and distinguish "
    "confirmed results from unresolved uncertainty. For substantial deliverables, use any "
    "selected Skill before drafting and review the result for completeness. Match the depth and "
    "format the user requested; reports and articles need developed structure, supporting "
    "evidence, and explicit limitations rather than a short generic summary. When a tool "
    "fails on a required step, inspect the failure and exhaust safe alternatives for that step "
    "without expanding into optional investigations before asking the "
    "user to retry. Do not expose internal "
    "model, runtime, or tool identifiers unless the user asks. Respond in the user's language."
    " For multi-step work, include a brief public update in assistant content alongside "
    "tool calls; do not add a separate model call just for an acknowledgement. "
    "Report meaningful received evidence or a path change early, not only a final answer. "
    "Do not narrate every routine call or repeat generic waiting text. "
    "These updates are public facts and next steps, never private chain-of-thought. "
    "Use counts/coverage first and fetch full records selectively; do not dump entire collections "
    "into context. Distinguish partial samples from complete coverage. For simple answers reply "
    "directly without an unnecessary preamble."
)


def build_worker_orchestrator(
    *,
    model_gateway: Any,
    policy_engine: Any,
    tool_gateway: Any,
    context_compiler: Any,
    cloud_continuation: Any,
    recorder: Any,
    event_store: Any,
    lifecycle_store: Any,
    cloud_artifacts: Any,
    local_continuation_store: Any,
    session_id: SessionId,
    provider_continuation: Any,
    invocation_policy: Any = None,
    public_output_policy: PublicOutputPolicy | None = None,
    worker_progress: WorkerProgressRecovery | None = None,
    user_input: str = "",
    attempt_number: int = 1,
    transient_output: TransientDeltaSink | None = None,
) -> SingleAttemptOrchestrator:
    persist_event, prepare_continuation = provider_runtime.build_worker_context_sinks(
        cloud_continuation,
        recorder=recorder,
        event_store=event_store,
        lifecycle_store=lifecycle_store,
        cloud_artifacts=cloud_artifacts,
        local_store=local_continuation_store,
        session_id=session_id,
    )
    if transient_output is not None and recorder.worker_mutation_authority is None:
        raise ValueError("transient output requires cloud authority and Worker progress")
    progress: ProgressiveEventSink | None = None
    if recorder.worker_mutation_authority is not None:
        if worker_progress is None:
            raise ValueError("cloud output requires prepared Worker progress")
        if (
            worker_progress.head.scope.namespace
            != recorder.worker_mutation_authority.deployment_namespace
        ):
            raise ValueError("Worker progress authority namespace mismatch")
        worker_progress.catch_up()
        if worker_progress.head.state.attempt_number != attempt_number:
            raise ValueError("Worker progress Attempt disagrees with execution")
        persist_event = worker_progress.persist_with(persist_event)
        if transient_output is not None:
            persist_event = transient_output.wrap(persist_event)
        policy = worker_progress.policy(public_output_policy or PublicOutputPolicy())
        progress = ProgressiveEventSink(
            persist_event,
            user_input=user_input,
            policy=policy,
            attempt_number=attempt_number,
            recovery_state=worker_progress.head.state,
            output_published=worker_progress.output_published,
            receipts_covered=worker_progress.receipts_covered,
            emission_scope=publication_scope,
            expression=PublicExpression(
                lambda messages, call_policy, deadline: model_gateway.complete(
                    messages, tools=(), invocation_policy=call_policy, deadline_s=deadline
                ),
                persist_event,
                max_calls=policy.expression_max_calls,
                deadline_s=policy.expression_deadline_seconds,
                max_input_characters=policy.expression_input_characters,
                max_output_tokens=policy.expression_output_tokens,
                calls_used=worker_progress.head.state.expression_calls_used,
                attempt_number=attempt_number,
            ),
        )
        recorder.effect_started_listener = progress.operation_started
        if isinstance(tool_gateway, FencedEffectToolGateway):
            tool_gateway.execution_finished_listener = _effect_terminal_observer(progress)
        persist_event = progress
    model_step = HarnessModelStep(
        context_compiler=context_compiler,
        available_tools=tool_gateway.model_tools,
        conversation_compactor=context_compiler,
        # ponytail: the provider profile already owns the physical context
        # ceiling and reserves. A second fixed ceiling caused needless prefix
        # rewrites long before DeepSeek's real window was under pressure.
        conversation_token_budget=CLOUD_CONVERSATION_TOKEN_BUDGET,
        event_sink=persist_event,
        continuation_sink=prepare_continuation,
        provider_continuation=provider_continuation,
        attempt_number=attempt_number,
        delta_coalesce_characters=progress.policy.delta_characters if progress else 256,
        delta_coalesce_seconds=progress.policy.delta_seconds if progress else 0.1,
        invocation_policy=invocation_policy,
        public_call_started=transient_output.start_public_call if transient_output else None,
    )
    return SingleAttemptOrchestrator(
        model_gateway,
        policy_engine,
        tool_gateway,
        model_step=model_step,
        synthesize_tool_results=True,
        parallel_safe_tools=tool_gateway.parallel_safe_tools,
        parallel_batch_limits=tool_gateway.parallel_batch_limits,
        max_parallel_tool_calls=3,
        tool_call_resolver=tool_gateway.resolve_model_tool_calls,
        event_sink=persist_event,
        close_sink=(lambda: _close_output(progress, transient_output)) if progress else None,
    )


def _close_output(progress: ProgressiveEventSink, transient: TransientDeltaSink | None) -> None:
    if transient is None:
        progress.close()
        return
    with publication_scope(monotonic() + output_lifecycle.PUBLIC_OUTPUT_CLOSE_SECONDS):
        try:
            progress.close()
        finally:
            try:
                transient.close()
            except TimeoutError:
                pass  # Failed draft references remain; canonical timer failures still propagate.


def _effect_terminal_observer(
    progress: ProgressiveEventSink,
) -> Callable[[ToolCall, ToolResult | None], None]:
    def observe(tool_call: ToolCall, result: ToolResult | None) -> None:
        # Observation only: the Effect store/recorder already owns durable terminal Events.
        # The gateway invokes this after mutation(), including when its terminal commit fails.
        progress.observe_operation_result(
            HarnessEventDraft(
                EventType.TOOL_EXECUTION_COMPLETED
                if result is not None and result.status is ToolCallStatus.EXECUTED
                else EventType.TOOL_EXECUTION_FAILED,
                EventActor.TOOL,
                {
                    "tool_call_id": str(tool_call.tool_call_id),
                    "status": ToolCallStatus.FAILED.value
                    if result is None
                    else result.status.value,
                    "metadata": {} if result is None else result.metadata,
                },
            )
        )

    return observe


def harness_task_for_recovered(
    task: RecoveredTask,
    *,
    network_profile: Any,
    tool_gateway: Any,
    memory_store: MemoryReadPort,
    personalization_store: UserPersonalizationStorePort | None = None,
    materialization: ContextMaterialization | None = None,
) -> HarnessTask:
    runtime_evidence = _without_materialized_capsule(
        task.runtime_evidence,
        materialization,
    )
    confirmed_memories: tuple[ConfirmedMemoryInput, ...]
    if materialization is None:
        confirmed_memories = list_confirmed_repo_memories(
            memory_store,
            repo_id=str(task.workspace_root.resolve()),
            query_text=task.user_input,
        )
    else:
        inputs = context_inputs_from_materialization(materialization)
        runtime_evidence = (*runtime_evidence, *inputs.runtime_evidence)
        confirmed_memories = inputs.confirmed_memories
    if task.delegated_context is not None:
        inherited = context_inputs_from_delegated_snapshot(task.delegated_context)
        runtime_evidence = (*runtime_evidence, *inherited.runtime_evidence)
        confirmed_memories = (*confirmed_memories, *inherited.confirmed_memories)
    return HarnessTask(
        title=task.title,
        user_input=task.user_input,
        max_attempts=task.max_attempts,
        max_model_calls=task.max_model_calls,
        max_tool_calls=task.max_tool_calls,
        workspace_root=task.workspace_root,
        policy_profile=task.policy_profile,
        tool_profile=task.tool_profile,
        network_profile=network_profile.name.value,
        network_allowlist=network_profile.domain_allowlist,
        mcp_allowlist=tuple(tool.name for tool in tool_gateway.effective_mcp_tools),
        skill_components=tool_gateway.effective_skill_components,
        skill_requirements=getattr(tool_gateway, "effective_skill_requirements", ()),
        context_token_budget=(
            CLOUD_CONTEXT_TOKEN_BUDGET
            if materialization is not None or task.delegated_context is not None
            else 200
        ),
        confirmed_memories=_deduplicate_memories(confirmed_memories),
        attachments=task.attachments,
        image_attachments=task.image_attachments,
        conversation_history=task.conversation_history,
        runtime_evidence=runtime_evidence,
        identity_directive=(
            HOST_EMBEDDED_AGENT_IDENTITY_DIRECTIVE if task.host_context is not None else None
        ),
        user_instructions=_user_instructions(task, personalization_store),
        acceptance_contract=task.acceptance_contract,
    )


def _user_instructions(
    task: RecoveredTask,
    store: UserPersonalizationStorePort | None,
) -> str | None:
    if store is None or task.host_context is None:
        return None
    principals = tuple(
        ref.resource_id
        for ref in task.host_context.resource_refs
        if ref.resource_type == "principal"
    )
    if len(principals) != 1:
        return None
    record = store.get(principals[0])
    return None if record is None else record.instructions


def _without_materialized_capsule(
    evidence: tuple[RuntimeEvidenceInput, ...],
    materialization: ContextMaterialization | None,
) -> tuple[RuntimeEvidenceInput, ...]:
    capsule = None if materialization is None else materialization.active_capsule
    if capsule is None:
        return evidence
    return tuple(
        item for item in evidence if (item.metadata or {}).get("capsule_id") != capsule.capsule_id
    )


def _deduplicate_memories(
    memories: tuple[ConfirmedMemoryInput, ...],
) -> tuple[ConfirmedMemoryInput, ...]:
    seen: set[tuple[object, str]] = set()
    selected: list[ConfirmedMemoryInput] = []
    for memory in memories:
        key = memory.memory_type, memory.text
        if key in seen:
            continue
        seen.add(key)
        selected.append(memory)
    return tuple(selected)
