from datetime import UTC, datetime

import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.plans import PlanStep, PlanStepStatus, SessionPlan
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessContext,
    HarnessModelStep,
    HarnessTask,
)
from agent_core.harness.hooks import NoopVerifier
from agent_core.harness.orchestrator import SingleAttemptOrchestrator
from agent_core.ports.tool_gateway import ToolGatewayPort
from agent_security import LocalPolicyEngine, PolicyProfile

NOW = datetime(2026, 7, 15, 13, 0, tzinfo=UTC)


def test_session_plan_enforces_unique_ids_and_one_active_step() -> None:
    plan = SessionPlan(
        steps=(PlanStep(step_id="gather", content="Gather evidence", status="in_progress"),)
    )
    assert plan.summary["in_progress"] == 1
    with pytest.raises(ValueError, match="unique"):
        SessionPlan(
            steps=(
                PlanStep(step_id="same", content="First", status="pending"),
                PlanStep(step_id="same", content="Second", status="completed"),
            )
        )
    with pytest.raises(ValueError, match="at most one"):
        SessionPlan(
            steps=(
                PlanStep(step_id="one", content="First", status="in_progress"),
                PlanStep(step_id="two", content="Second", status="in_progress"),
            )
        )


def test_plan_updated_event_projects_authoritative_plan() -> None:
    session = Session.create(title="Plan", created_at=NOW).model_copy(
        update={"status": SessionStatus.RUNNING}
    )
    event = SessionEvent.create(
        session_id=session.session_id,
        sequence=1,
        event_type=EventType.PLAN_UPDATED,
        actor=EventActor.HARNESS,
        payload={
            "steps": [
                {"step_id": "answer", "content": "Prepare answer", "status": "pending"}
            ]
        },
        created_at=NOW,
    )
    projected = apply_event(session, event)
    assert projected.task_plan.steps[0].step_id == "answer"
    assert projected.task_plan.updated_at == NOW


def test_agent_plan_updates_and_returns_full_plan_without_gateway_execution() -> None:
    plan_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.plan",
        arguments={
            "steps": [
                {"step_id": "gather", "content": "Gather evidence", "status": "completed"},
                {"step_id": "answer", "content": "Prepare answer", "status": "in_progress"},
            ]
        },
        created_at=NOW,
        provider_call_id="call_plan",
    )
    gateway = ScriptedModelGateway(
        responses=(
            _response("I will make a plan.", plan_call),
            _response("Plan recorded."),
            _response("Plan recorded."),
        )
    )
    session = Session.create(title="Plan", created_at=NOW).model_copy(
        update={"status": SessionStatus.RUNNING}
    )
    result = SingleAttemptOrchestrator(
        gateway,
        LocalPolicyEngine(PolicyProfile.READ_ONLY),
        NeverToolGateway(),
        model_step=HarnessModelStep(),
        verifier=NoopVerifier(),
        synthesize_tool_results=True,
    ).run(
        HarnessContext(
            task=HarnessTask(title="Plan", user_input="Prepare a summary."),
            session=session,
            attempt=HarnessAttempt(number=1, started_at=NOW),
        )
    )
    plan_events = [
        event
        for event in result.emitted_events
        if event.event_type is EventType.PLAN_UPDATED
    ]
    assert len(plan_events) == 1
    assert plan_events[0].payload["steps"][1]["status"] == "in_progress"
    assert '"total":2' in gateway.requests[1][-1].content
    assert result.metadata["tool_calls_executed"] == 1


def test_invalid_agent_plan_fails_before_tool_or_durable_events() -> None:
    invalid_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="agent.plan",
        arguments={
            "steps": [
                {"step_id": "same", "content": "First", "status": "pending"},
                {"step_id": "same", "content": "Second", "status": "completed"},
            ]
        },
        created_at=NOW,
    )
    gateway = ScriptedModelGateway(responses=(_response("Invalid plan.", invalid_call),))
    session = Session.create(title="Plan", created_at=NOW).model_copy(
        update={"status": SessionStatus.RUNNING}
    )

    result = SingleAttemptOrchestrator(
        gateway,
        LocalPolicyEngine(PolicyProfile.READ_ONLY),
        NeverToolGateway(),
        model_step=HarnessModelStep(),
        verifier=NoopVerifier(),
    ).run(
        HarnessContext(
            task=HarnessTask(title="Plan", user_input="Prepare a summary."),
            session=session,
            attempt=HarnessAttempt(number=1, started_at=NOW),
        )
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "invalid_plan_request"
    assert EventType.PLAN_UPDATED not in {event.event_type for event in result.emitted_events}
    assert EventType.TOOL_EXECUTION_STARTED not in {
        event.event_type for event in result.emitted_events
    }


def test_recovered_active_plan_is_injected_without_completed_steps() -> None:
    task = HarnessTask(
        title="Resume",
        user_input="Continue.",
        task_plan=SessionPlan(
            steps=(
                PlanStep(step_id="done", content="Already done", status=PlanStepStatus.COMPLETED),
                PlanStep(step_id="next", content="Continue work", status=PlanStepStatus.PENDING),
            )
        ),
    )
    messages = HarnessModelStep().build_initial_messages(task, created_at=NOW)
    assert "Continue work" in messages[0].content
    assert "Already done" not in messages[0].content


def _response(content: str, tool_call: ToolCall | None = None) -> ScriptedModelResponse:
    return ScriptedModelResponse(
        completion=ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=content,
                created_at=NOW,
            ),
            tool_calls=(tool_call,) if tool_call is not None else (),
        )
    )


class NeverToolGateway(ToolGatewayPort):
    def execute(self, tool_call: ToolCall) -> ToolResult:
        raise AssertionError(f"unexpected gateway execution: {tool_call.name}")
