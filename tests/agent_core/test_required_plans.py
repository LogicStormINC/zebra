from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.plans import PlanStep, SessionPlan
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessLoop,
    HarnessModelStep,
    HarnessStopReason,
    HarnessTask,
    ToolCallSelection,
    ToolCallSelectionStrategy,
)
from agent_core.harness.hooks import NoopVerifier
from agent_core.harness.orchestrator import SingleAttemptOrchestrator
from agent_core.ports.tool_gateway import ToolGatewayPort
from agent_security import LocalPolicyEngine, PolicyProfile

NOW = datetime(2026, 8, 10, 13, 0, tzinfo=UTC)
TOOLS = (
    ModelToolDefinition(
        name="agent.plan",
        description="Maintain the durable Plan.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="files.read",
        description="Read one file.",
        parameters={"type": "object", "properties": {}},
    ),
)


def test_required_plan_blocks_repeated_direct_final() -> None:
    result, gateway, tools = _run(
        _response("Done without a Plan."),
        _response("Still done without a Plan."),
        plan_required=True,
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "required_plan_not_created"
    assert tools.calls == []
    assert gateway.requests[1][-1].metadata["required_plan_nudge"] is True


def test_required_plan_blocks_non_plan_tools_until_plan_exists() -> None:
    discarded = _call("files.read", {"path": "first.txt"})
    rejected = _call("files.read", {"path": "second.txt"})
    result, _, tools = _run(
        _response("Read first.", discarded),
        _response("Read anyway.", rejected),
        plan_required=True,
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "required_plan_not_created"
    assert tools.calls == []
    assert not {
        str(event.payload.get("tool_call_id"))
        for event in result.emitted_events
        if event.event_type
        in {
            EventType.TOOL_CALL_PROPOSED,
            EventType.POLICY_DECISION_MADE,
            EventType.TOOL_EXECUTION_STARTED,
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
        }
    } & {str(discarded.tool_call_id), str(rejected.tool_call_id)}


def test_required_plan_update_precedes_business_tool_execution() -> None:
    discarded = _call("files.read", {"path": "evidence.txt"})
    planned = _call("files.read", {"path": "evidence.txt"})
    open_plan = _plan_call("in_progress")
    close_plan = _plan_call("completed")
    result, _, tools = _run(
        _response("Read first.", discarded),
        _response("Plan, then read.", open_plan, planned),
        _response("Close the Plan.", close_plan),
        _response("Final answer."),
        _response("Final answer."),
        plan_required=True,
        parallel_safe_tools=frozenset({"agent.plan", "files.read"}),
    )

    plan_index = next(
        index
        for index, event in enumerate(result.emitted_events)
        if event.event_type is EventType.PLAN_UPDATED
    )
    read_index = next(
        index
        for index, event in enumerate(result.emitted_events)
        if event.event_type is EventType.TOOL_EXECUTION_STARTED
        and event.payload.get("tool_name") == "files.read"
    )
    assert result.outcome is HarnessAttemptOutcome.COMPLETED
    assert plan_index < read_index
    assert tools.calls == [planned]


def test_required_plan_cannot_be_skipped_by_tool_selection() -> None:
    plan = _plan_call("completed")
    read = _call("files.read", {"path": "evidence.txt"})
    result, _, tools = _run(
        _response("Plan first, then read.", plan, read),
        _response("Final answer."),
        _response("Final answer."),
        plan_required=True,
        synthesize_tool_results=False,
        tool_selector=LastToolCallSelectionStrategy(),
    )

    assert result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.calls == []
    assert EventType.PLAN_UPDATED in {event.event_type for event in result.emitted_events}


def test_required_plan_is_preserved_when_batch_exceeds_tool_budget() -> None:
    plan = _plan_call("completed")
    read = _call("files.read", {"path": "evidence.txt"})
    result, _, tools = _run(
        _response("Plan first, then read.", plan, read),
        _response("Final answer."),
        _response("Final answer."),
        plan_required=True,
        max_tool_calls=1,
    )

    assert result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.calls == []
    assert EventType.PLAN_UPDATED in {event.event_type for event in result.emitted_events}


def test_required_plan_rejects_empty_plan_before_business_tool() -> None:
    empty = _call("agent.plan", {"steps": []})
    read = _call("files.read", {"path": "evidence.txt"})
    result, _, tools = _run(
        _response("Empty Plan, then read.", empty, read),
        _response("Final anyway."),
        plan_required=True,
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "required_plan_not_created"
    assert tools.calls == []
    assert EventType.PLAN_UPDATED not in {event.event_type for event in result.emitted_events}


def test_required_plan_rejects_invalid_plan_before_business_tool() -> None:
    invalid = _call(
        "agent.plan",
        {"steps": [{"step_id": "read", "status": "in_progress"}]},
    )
    read = _call("files.read", {"path": "evidence.txt"})
    result, _, tools = _run(
        _response("Invalid Plan, then read.", invalid, read),
        _response("Final anyway."),
        plan_required=True,
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "required_plan_not_created"
    assert tools.calls == []


def test_required_plan_blocks_approved_business_tool_without_plan() -> None:
    read = _call("files.read", {"path": "approved.txt"})
    completion = _response("Run the approved read.", read).completion
    tools = RecordingToolGateway()
    orchestrator = SingleAttemptOrchestrator(
        ScriptedModelGateway(responses=(_response("unused"),)),
        LocalPolicyEngine(PolicyProfile.READ_ONLY),
        tools,
        model_step=HarnessModelStep(available_tools=TOOLS),
        verifier=NoopVerifier(),
        synthesize_tool_results=True,
    )

    result = orchestrator.continue_approved_tool_call(
        _context(plan_required=True),
        initial_completion=completion,
        tool_call=read,
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "required_plan_not_created"
    assert tools.calls == []


def test_required_plan_completion_backstop_prevents_retry_and_success() -> None:
    attempts = 0

    def complete_without_plan(_context: HarnessContext) -> HarnessAttemptResult:
        nonlocal attempts
        attempts += 1
        return HarnessAttemptResult(
            outcome=HarnessAttemptOutcome.COMPLETED,
            summary="incorrect success",
        )

    result = HarnessLoop().run(
        HarnessTask(
            title="Required Plan",
            user_input="Complete the Goal.",
            plan_required=True,
            max_attempts=2,
        ),
        complete_without_plan,
        created_at=NOW,
    )

    assert attempts == 1
    assert result.run_result.stop_reason is HarnessStopReason.REQUIRED_PLAN_NOT_CREATED
    assert result.session.status is SessionStatus.FAILED


def test_required_plan_without_plan_capable_correction_budget_fails_closed() -> None:
    result, gateway, _ = _run(
        _response("Done without a Plan."),
        plan_required=True,
        max_model_calls=2,
    )

    assert result.outcome is HarnessAttemptOutcome.FAILED
    assert result.metadata["stop_reason"] == "required_plan_not_created"
    assert len(gateway.requests) == 1


def test_default_task_executes_one_tool_without_plan_or_nudge() -> None:
    read = _call("files.read", {"path": "one.txt"})
    result, gateway, tools = _run(
        _response("Read it.", read),
        _response("Final answer."),
        _response("Final answer."),
    )

    assert result.outcome is HarnessAttemptOutcome.COMPLETED
    assert tools.calls == [read]
    assert EventType.PLAN_UPDATED not in {event.event_type for event in result.emitted_events}
    assert all(
        message.metadata.get("required_plan_nudge") is not True
        for request in gateway.requests
        for message in request
    )


def test_existing_closed_durable_plan_satisfies_activation_contract() -> None:
    plan = SessionPlan(
        steps=(PlanStep(step_id="done", content="Already done", status="completed"),),
        updated_at=NOW,
    )
    result, gateway, _ = _run(
        _response("Final answer."),
        plan_required=True,
        task_plan=plan,
    )

    assert result.outcome is HarnessAttemptOutcome.COMPLETED
    assert len(gateway.requests) == 1


def _run(
    *responses: ScriptedModelResponse,
    plan_required: bool = False,
    max_model_calls: int | None = None,
    max_tool_calls: int | None = None,
    task_plan: SessionPlan | None = None,
    parallel_safe_tools: frozenset[str] = frozenset(),
    synthesize_tool_results: bool = True,
    tool_selector: ToolCallSelectionStrategy | None = None,
):
    gateway = ScriptedModelGateway(responses=responses)
    tools = RecordingToolGateway()
    plan = task_plan or SessionPlan()
    session = Session.create(title="Required Plan", created_at=NOW).model_copy(
        update={"status": SessionStatus.RUNNING, "task_plan": plan}
    )
    result = SingleAttemptOrchestrator(
        gateway,
        LocalPolicyEngine(PolicyProfile.READ_ONLY),
        tools,
        model_step=HarnessModelStep(available_tools=TOOLS),
        verifier=NoopVerifier(),
        synthesize_tool_results=synthesize_tool_results,
        tool_selector=tool_selector,
        parallel_safe_tools=parallel_safe_tools,
        max_parallel_tool_calls=2,
    ).run(
        _context(
            plan_required=plan_required,
            max_model_calls=max_model_calls,
            max_tool_calls=max_tool_calls,
            task_plan=plan,
            session=session,
        )
    )
    return result, gateway, tools


def _context(
    *,
    plan_required: bool,
    max_model_calls: int | None = None,
    max_tool_calls: int | None = None,
    task_plan: SessionPlan | None = None,
    session: Session | None = None,
) -> HarnessContext:
    plan = task_plan or SessionPlan()
    return HarnessContext(
        task=HarnessTask(
            title="Required Plan",
            user_input="Handle the evidence.",
            goal="Complete the durable evidence goal.",
            plan_required=plan_required,
            max_model_calls=max_model_calls,
            max_tool_calls=max_tool_calls,
            task_plan=plan,
        ),
        session=session
        or Session.create(title="Required Plan", created_at=NOW).model_copy(
            update={"status": SessionStatus.RUNNING, "task_plan": plan}
        ),
        attempt=HarnessAttempt(number=1, started_at=NOW),
    )


def _plan_call(status: str) -> ToolCall:
    return _call(
        "agent.plan",
        {
            "steps": [
                {
                    "step_id": "read",
                    "content": "Read the evidence",
                    "status": status,
                }
            ]
        },
    )


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
    )


def _response(content: str, *tool_calls: ToolCall) -> ScriptedModelResponse:
    return ScriptedModelResponse(
        completion=ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=content,
                created_at=NOW,
            ),
            tool_calls=tool_calls,
        )
    )


class RecordingToolGateway(ToolGatewayPort):
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="evidence",
        )


class LastToolCallSelectionStrategy:
    def select(self, tool_calls: tuple[ToolCall, ...]) -> ToolCallSelection:
        return ToolCallSelection(
            tool_call=tool_calls[-1],
            summary="selected last tool call",
            metadata={"selected_index": len(tool_calls) - 1},
        )
