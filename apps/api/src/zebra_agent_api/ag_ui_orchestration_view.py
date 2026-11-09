"""CA-P7-02C production wiring: orchestration view into the AG-UI task view.

When a task is the PARENT of an orchestration run (orchestration_runs.
parent_task_id) the canonical task view gains a public orchestration state
object; tasks without a run keep an unchanged view.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.identifiers import TaskId
from agent_integrations.ag_ui.orchestration_state import (
    orchestration_projection_view,
)


def task_orchestration_view(stores: Any, task_id: TaskId) -> dict[str, object] | None:
    """Attach the plan-14.2 orchestration state to a parent task's view.

    Returns None for tasks with no orchestration run (the common case) or
    when the orchestration store is not configured — the task view must
    never fail because orchestration facts are absent.
    """

    orchestration = getattr(stores, "orchestration", None)
    if orchestration is None:
        return None
    finder = getattr(orchestration, "find_run_for_parent", None)
    if finder is None:
        return None
    run_ref = finder(task_id)
    if run_ref is None:
        return None
    try:
        return orchestration_projection_view(orchestration, run_ref)
    except Exception:
        # An unreadable orchestration projection must not break the task view.
        return None
