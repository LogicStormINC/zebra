from datetime import datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.harness.models import HarnessTask


def append_task_state_context(
    messages: list[SessionMessage],
    task: HarnessTask,
    *,
    created_at: datetime,
    goal_anchor_present: bool = False,
) -> None:
    """Append SYSTEM task-state context.

    W5-P3A (Finding 1 fix): the "Stable task goal" SYSTEM block is
    emitted only when ``goal_anchor_present`` is True. The first
    USER_MESSAGE_RECEIVED body is ordinary USER history; it must
    never be re-injected as a SYSTEM Stable Task Goal.
    """
    if goal_anchor_present and task.stable_goal and task.stable_goal != task.user_input:
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.SYSTEM,
                content=f"Stable task goal:\n{task.stable_goal}",
                created_at=created_at,
            )
        )
    active_steps = tuple(
        step
        for step in task.task_plan.steps
        if step.status.value in {"pending", "in_progress"}
    )
    if active_steps:
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.SYSTEM,
                content="\n".join(
                    ["Current durable task plan:"]
                    + [
                        f"- [{step.status.value}] {step.step_id}: {step.content}"
                        for step in active_steps
                    ]
                ),
                created_at=created_at,
            )
        )
