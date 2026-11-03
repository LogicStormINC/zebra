"""Resolve control-plane workspace references onto recovered tasks."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from agent_core.domain.identifiers import SessionId

from zebra_agent_worker.task_recovery import RecoveredTask

if TYPE_CHECKING:
    from agent_runtime.workspace_runtime_resolver import WorkspaceRuntimeResolver


def apply_workspace_resolver(
    task: RecoveredTask,
    resolver: WorkspaceRuntimeResolver,
    session_id: SessionId,
) -> RecoveredTask:
    """Plain paths pass through; workspace:// refs resolve fail-closed."""
    reference = str(task.workspace_root)
    if not reference.startswith("workspace:"):
        return task
    resolved = resolver.resolve(reference, session_id=session_id)
    if str(resolved) == reference:
        return task
    return replace(task, workspace_root=resolved)


def plan_host_workspace(
    task: RecoveredTask, resolver: WorkspaceRuntimeResolver, session_id: SessionId,
) -> tuple[RecoveredTask, str | None]:
    """Use only a trusted logical target; actual file access still needs resolution."""
    reference = str(task.workspace_root)
    root = resolver.planned_host_root(reference, session_id=session_id)
    if root is None:
        return apply_workspace_resolver(task, resolver, session_id), None
    return replace(task, workspace_root=root), reference
