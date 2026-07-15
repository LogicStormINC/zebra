import json

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.plans import SessionPlan
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.hooks import VerifierHook
from agent_core.harness.models import HarnessContext, HarnessEventDraft
from agent_core.harness.tool_execution import ToolExecutionStep, record_tool_result


def execute_plan_call(
    context: HarnessContext,
    tool_call: ToolCall,
    *,
    verifier: VerifierHook,
    emitted_events: list[HarnessEventDraft],
) -> ToolExecutionStep:
    plan = _current_plan(context, emitted_events)
    updated = "steps" in tool_call.arguments
    if updated:
        plan = SessionPlan.model_validate({"steps": tool_call.arguments["steps"]})
    emitted_events.append(
        HarnessEventDraft(
            event_type=EventType.TOOL_EXECUTION_STARTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": context.attempt.number,
                "tool_name": tool_call.name,
                "tool_call_id": str(tool_call.tool_call_id),
            },
        )
    )
    if updated:
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.PLAN_UPDATED,
                actor=EventActor.HARNESS,
                payload={"steps": [step.model_dump(mode="json") for step in plan.steps]},
            )
        )
    result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output=json.dumps(plan.to_mapping(), separators=(",", ":"), ensure_ascii=False),
        metadata={"plan_updated": updated, **plan.summary},
    )
    return record_tool_result(
        context,
        tool_call,
        result,
        verifier=verifier,
        emitted_events=emitted_events,
    )


def _current_plan(
    context: HarnessContext,
    emitted_events: list[HarnessEventDraft],
) -> SessionPlan:
    for event in reversed(emitted_events):
        if event.event_type is EventType.PLAN_UPDATED:
            return SessionPlan.model_validate({"steps": event.payload.get("steps", ())})
    return context.session.task_plan
