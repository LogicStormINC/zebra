from agent_core.domain.plans import SessionPlan


def serialize_task_plan(plan: SessionPlan) -> dict[str, object] | None:
    if not plan.steps:
        return None
    return plan.to_mapping()
