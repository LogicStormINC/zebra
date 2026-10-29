"""Activities describe observed work; Step closure needs an explicit matching state."""

from ag_ui.core import ActivitySnapshotEvent, Event, StepFinishedEvent, StepStartedEvent
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.plans import PlanStepStatus, SessionPlan

from agent_integrations.ag_ui.payload_validation import required_payload_text
from agent_integrations.ag_ui.standard_state import StandardProjectionState


def activity(
    key: str,
    activity_type: str,
    content: dict[str, object],
    timestamp: int,
) -> ActivitySnapshotEvent:
    return ActivitySnapshotEvent(
        timestamp=timestamp,
        message_id=key,
        activity_type=activity_type,
        content=content,
        replace=True,
    )


def project_activity(event: SessionEvent, state: StandardProjectionState) -> tuple[Event, ...]:
    timestamp = int(event.created_at.timestamp() * 1000)
    if event.event_type is EventType.PLAN_UPDATED:
        plan = SessionPlan.model_validate({"steps": event.payload.get("steps")})
        frames: list[Event] = [
            activity(
                "plan:" + str(state.protocol_run_id),
                "plan",
                {"steps": [s.model_dump(mode="json") for s in plan.steps]},
                timestamp,
            )
        ]
        previous = state.active_step
        old = next((s for s in plan.steps if s.step_id == previous), None)
        if (
            old is not None
            and old.content == state.active_step_content
            and old.status in {PlanStepStatus.COMPLETED, PlanStepStatus.CANCELLED}
        ):
            frames.append(
                StepStartedEvent(
                    timestamp=state.active_step_started_at,
                    step_name=str(state.active_step_name),
                    metadata={"zebra": {"planStepId": previous, "timing": "observed_transition"}},
                )
            )
            frames.append(
                StepFinishedEvent(
                    timestamp=timestamp,
                    step_name=str(state.active_step_name),
                    metadata={"zebra": {"status": old.status.value}},
                )
            )
        active = next(
            (s.step_id for s in plan.steps if s.status is PlanStepStatus.IN_PROGRESS), None
        )
        content = next((s.content for s in plan.steps if s.step_id == active), None)
        if active is not None and (active != previous or content != state.active_step_content):
            # A replacement/re-entry is a new observed Step span, never the old span's success.
            state.active_step_name = f"{active}:{event.event_id}"
            state.active_step_started_at = timestamp
        if active is None:
            state.active_step_name = None
            state.active_step_started_at = None
        state.active_step = active
        state.active_step_content = content
        return tuple(frames)
    if event.event_type is EventType.TESTS_COMPLETED:
        # No durable start exists; expose only the completion fact, without duration.
        return (
            activity("tests:" + str(event.event_id), "tests", {"status": "completed"}, timestamp),
        )
    if event.event_type is EventType.TOOL_EXECUTION_STARTED:
        call = required_payload_text(event.payload, "tool_call_id")
        state.executing_tools.add(call)
        if (
            state.pending_tools.get(call) == "agent.research"
            or event.payload.get("tool_name") == "agent.research"
        ):
            state.subagent_usage_unknown = True
        return (
            activity(
                "execution:" + call,
                "tool_execution",
                {
                    "tool_call_id": call,
                    "status": "running",
                },
                timestamp,
            ),
        )
    return ()
