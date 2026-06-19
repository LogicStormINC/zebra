from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessContext,
    HarnessLoop,
    HarnessTask,
    PlannerResult,
    SingleAttemptOrchestrator,
    VerifierResult,
)


class AllowAllPolicyEngine:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed in hook test",
            policy_profile="test",
        )


class StaticToolGateway:
    def __init__(self, result: ToolResult) -> None:
        self._result = result

    def execute(self, _tool_call: ToolCall) -> ToolResult:
        return self._result


class RecordingPlanner:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def plan(self, context: HarnessContext) -> PlannerResult:
        self.calls.append(context.attempt.number)
        return PlannerResult(
            summary="planner prepared the attempt",
            metadata={"attempt_number": context.attempt.number},
        )


class RecordingVerifier:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def verify(
        self,
        context: HarnessContext,
        tool_status: str,
        tool_output: str,
    ) -> VerifierResult:
        self.calls.append((context.attempt.number, tool_status))
        return VerifierResult(
            summary="verifier inspected tool output",
            passed=tool_status == "executed",
            metadata={"tool_output": tool_output},
        )


def test_single_attempt_orchestrator_runs_planner_and_verifier_hooks() -> None:
    created_at = datetime(2026, 6, 20, 1, 0, tzinfo=UTC)
    tool_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={"path": "README.md"},
        created_at=created_at,
    )
    gateway = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="I will inspect README.",
                        created_at=created_at,
                    ),
                    tool_calls=(tool_call,),
                )
            ),
        )
    )
    planner = RecordingPlanner()
    verifier = RecordingVerifier()
    tool_result = ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="readme body",
        metadata={"path": "README.md"},
    )
    orchestrator = SingleAttemptOrchestrator(
        gateway,
        AllowAllPolicyEngine(),
        StaticToolGateway(tool_result),
        planner=planner,
        verifier=verifier,
    )
    loop = HarnessLoop()

    result = loop.run(
        HarnessTask(title="Inspect", user_input="Inspect README."),
        orchestrator.run,
        created_at=created_at,
    )

    assert planner.calls == [1]
    assert verifier.calls == [(1, "executed")]
    assert result.attempt_result.metadata["plan_summary"] == "planner prepared the attempt"
    assert (
        result.attempt_result.metadata["verification_summary"]
        == "verifier inspected tool output"
    )
    assert result.attempt_result.metadata["verification_passed"] is True
    assert EventType.PLAN_PROPOSED in [event.event_type for event in result.events]
    assert EventType.TESTS_COMPLETED in [event.event_type for event in result.events]
