"""Build the immutable Harness task view from recovered Worker state."""

from typing import Any

from agent_context import (
    context_inputs_from_delegated_snapshot,
    context_inputs_from_materialization,
)
from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.harness import HarnessTask
from agent_core.ports import MemoryReadPort
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput
from agent_storage import list_confirmed_repo_memories

from zebra_agent_worker.task_recovery import RecoveredTask

CLOUD_CONTEXT_TOKEN_BUDGET = 2_048


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
        runtime_evidence=runtime_evidence,
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
