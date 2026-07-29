"""Build the immutable Harness task view from recovered Worker state."""

from typing import Any

from agent_core.harness import HarnessTask
from agent_core.ports import MemoryStorePort
from agent_storage import list_confirmed_repo_memories

from zebra_agent_worker.task_recovery import RecoveredTask


def harness_task_for_recovered(
    task: RecoveredTask,
    *,
    network_profile: Any,
    tool_gateway: Any,
    memory_store: MemoryStorePort,
) -> HarnessTask:
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
        confirmed_memories=list_confirmed_repo_memories(
            memory_store,
            repo_id=str(task.workspace_root.resolve()),
            query_text=task.user_input,
        ),
        attachments=task.attachments,
        runtime_evidence=task.runtime_evidence,
    )
