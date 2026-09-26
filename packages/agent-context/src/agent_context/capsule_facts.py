from dataclasses import dataclass

from agent_core.domain.events import EventType, SessionEvent


@dataclass(frozen=True, slots=True)
class CapsuleWorkFacts:
    plan: tuple[str, ...] = ()
    completed_actions: tuple[str, ...] = ()
    pending_actions: tuple[str, ...] = ()
    rejected_approaches: tuple[str, ...] = ()


def capsule_work_facts(events: list[SessionEvent]) -> CapsuleWorkFacts:
    """Project the latest structured plan without guessing from prose."""
    for event in reversed(events):
        if event.event_type is not EventType.PLAN_UPDATED:
            continue
        steps = event.payload.get("steps")
        if not isinstance(steps, list):
            continue
        plan: list[str] = []
        completed: list[str] = []
        pending: list[str] = []
        rejected: list[str] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            content = step.get("content")
            status = step.get("status")
            if not isinstance(content, str) or not content.strip():
                continue
            normalized = content.strip()
            plan.append(normalized)
            if status == "completed":
                completed.append(normalized)
            elif status in {"pending", "in_progress"}:
                pending.append(normalized)
            elif status == "cancelled":
                rejected.append(normalized)
        return CapsuleWorkFacts(
            plan=tuple(plan),
            completed_actions=tuple(completed),
            pending_actions=tuple(pending),
            rejected_approaches=tuple(rejected),
        )
    legacy_plan = tuple(
        summary
        for event in events
        if event.event_type in {EventType.PLAN_PROPOSED, EventType.PLAN_UPDATED}
        and (summary := _text(event.payload, "summary")) is not None
    )[-8:]
    return CapsuleWorkFacts(plan=legacy_plan, pending_actions=legacy_plan)


def capsule_permission_boundaries(events: list[SessionEvent]) -> tuple[str, ...]:
    return tuple(
        _permission_state(event)
        for event in events
        if event.event_type
        in {
            EventType.POLICY_DECISION_MADE,
            EventType.APPROVAL_REQUESTED,
            EventType.APPROVAL_GRANTED,
            EventType.APPROVAL_REJECTED,
        }
    )


def _permission_state(event: SessionEvent) -> str:
    detail = next(
        (
            value.strip()
            for key in ("decision", "reason", "status")
            if isinstance((value := event.payload.get(key)), str) and value.strip()
        ),
        "recorded",
    )
    return f"{event.event_type.value}:{detail}"


def _text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
