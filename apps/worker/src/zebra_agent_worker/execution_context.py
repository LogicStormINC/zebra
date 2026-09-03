"""Build the immutable Harness task view from recovered Worker state."""

from typing import Any

from agent_context import (
    context_inputs_from_delegated_snapshot,
    context_inputs_from_materialization,
)
from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.identifiers import SessionId
from agent_core.harness import HarnessModelStep, HarnessTask, SingleAttemptOrchestrator
from agent_core.ports import MemoryReadPort
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput
from agent_storage import list_confirmed_repo_memories

import zebra_agent_worker.provider_continuation_execution as provider_runtime
from zebra_agent_worker.task_recovery import RecoveredTask

CLOUD_CONTEXT_TOKEN_BUDGET = 2_048
CLOUD_CONVERSATION_TOKEN_BUDGET = 8_192
HOST_EMBEDDED_AGENT_IDENTITY_DIRECTIVE = (
    "You are the product assistant embedded by the invoking Host application. Follow the "
    "Host-provided product role and identity in the task context. Never identify yourself as "
    "the underlying agent runtime, an engineering assistant, or a coding assistant unless the "
    "Host explicitly defines that product role. Use the Host tools actually available in this "
    "session proactively, ask for required configuration only when it is missing, and never "
    "claim an operation succeeded without a successful tool result. Do not expose internal "
    "model, runtime, or tool identifiers unless the user asks. Respond in the user's language."
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
    model_step = HarnessModelStep(
        context_compiler=context_compiler,
        available_tools=tool_gateway.model_tools,
        conversation_compactor=context_compiler,
        conversation_token_budget=CLOUD_CONVERSATION_TOKEN_BUDGET,
        event_sink=persist_event,
        continuation_sink=prepare_continuation,
        provider_continuation=provider_continuation,
        attempt_number=1,
        delta_coalesce_characters=256,
        delta_coalesce_seconds=0.1,
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
    )


def harness_task_for_recovered(
    task: RecoveredTask,
    *,
    network_profile: Any,
    tool_gateway: Any,
    memory_store: MemoryReadPort,
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
        context_token_budget=(
            CLOUD_CONTEXT_TOKEN_BUDGET
            if materialization is not None or task.delegated_context is not None
            else 200
        ),
        confirmed_memories=_deduplicate_memories(confirmed_memories),
        attachments=task.attachments,
        conversation_history=task.conversation_history,
        runtime_evidence=runtime_evidence,
        identity_directive=(
            HOST_EMBEDDED_AGENT_IDENTITY_DIRECTIVE if task.host_context is not None else None
        ),
    )


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
