from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessStopReason,
    HarnessTask,
    SingleAttemptOrchestrator,
)

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
TOOLS = (
    ModelToolDefinition(
        name="files.read",
        description="Read a file.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="tests.run",
        description="Run tests.",
        parameters={"type": "object", "properties": {}},
    ),
)


class AllowAllPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class SequenceToolGateway:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=f"result:{tool_call.name}",
        )


class EvidenceToolGateway(SequenceToolGateway):
    read_only_tools = frozenset({"files.read"})
    mutation_tools = frozenset({"tests.run"})


def test_bounded_loop_executes_two_tools_before_final_answer() -> None:
    first = _tool_call("files.read", {"path": "input.txt"}, "call_read")
    second = _tool_call("tests.run", {"preset": "test"}, "call_test")
    gateway = _gateway(
        _completion("Read the input.", first),
        _completion("Validate the result.", second),
        _completion("The input is valid."),
    )
    tools = SequenceToolGateway()

    result = HarnessLoop().run(
        HarnessTask(
            title="Sequential task",
            user_input="Read and validate the input.",
            max_model_calls=3,
            max_tool_calls=2,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "The input is valid."
    assert result.run_result.model_calls_used == 3
    assert result.run_result.tool_calls_used == 2
    assert [call.name for call in tools.calls] == ["files.read", "tests.run"]
    assert gateway.tool_requests == (TOOLS, TOOLS, ())
    assert [message.role for message in gateway.requests[2]][-5:] == [
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.USER,
    ]


def test_identical_read_executes_again_after_a_successful_mutation() -> None:
    first_read = _tool_call("files.read", {"path": "state.json"}, "call_read_before")
    mutation = _tool_call("tests.run", {"preset": "mutate"}, "call_mutate")
    fresh_read = _tool_call("files.read", {"path": "state.json"}, "call_read_after")
    gateway = _gateway(
        _completion("Inspect current state.", first_read),
        _completion("Apply the change.", mutation),
        _completion("Verify current state.", fresh_read),
        _completion("The change is verified."),
    )
    tools = EvidenceToolGateway()

    result = HarnessLoop().run(
        HarnessTask(
            title="Mutate and verify",
            user_input="Change state and verify it.",
            max_model_calls=4,
            max_tool_calls=3,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert [call.provider_call_id for call in tools.calls] == [
        "call_read_before",
        "call_mutate",
        "call_read_after",
    ]
    assert result.attempt_result.metadata["mutation_epoch"] == 1
    assert result.attempt_result.metadata["verified_mutation_epoch"] == 1
    assert "unverified_mutation" not in result.attempt_result.metadata


def test_mutation_gets_one_bounded_fresh_evidence_turn_before_completion() -> None:
    mutation = _tool_call("tests.run", {"preset": "mutate"}, "call_mutate")
    verification = _tool_call("files.read", {"path": "state.json"}, "call_verify")
    gateway = _gateway(
        _completion("Apply the change.", mutation),
        _completion("The change is complete."),
        _completion("I will verify the result.", verification),
        _completion("The current state confirms the change."),
    )
    tools = EvidenceToolGateway()

    result = HarnessLoop().run(
        HarnessTask(
            title="Require evidence closure",
            user_input="Change state and report the result.",
            max_model_calls=4,
            max_tool_calls=2,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert [call.provider_call_id for call in tools.calls] == ["call_mutate", "call_verify"]
    assert any(
        "verify the current state" in message.content
        for message in gateway.requests[2]
        if message.role is MessageRole.USER
    )
    assert result.attempt_result.metadata["verified_mutation_epoch"] == 1


def test_unverified_mutation_suspends_with_a_truthful_partial_result() -> None:
    mutation = _tool_call("tests.run", {"preset": "mutate"}, "call_mutate")
    gateway = _gateway(
        _completion("Apply the change.", mutation),
        _completion("The change is complete."),
    )

    result = HarnessLoop().run(
        HarnessTask(
            title="Do not claim an unverified mutation",
            user_input="Change state and report the result.",
            max_model_calls=2,
            max_tool_calls=1,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            EvidenceToolGateway(),
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "verification_required"
    assert result.run_result.stop_reason is HarnessStopReason.VERIFICATION_REQUIRED
    assert result.events[-1].event_type is EventType.SESSION_SUSPENDED
    assert "Verification status: unverified" in str(
        result.attempt_result.metadata["assistant_message"]
    )


def test_selected_skill_cannot_complete_when_skill_tools_are_unavailable() -> None:
    result = HarnessLoop().run(
        HarnessTask(
            title="Unavailable selected Skill",
            user_input="Use the selected Skill.",
            skill_components=("better-writing",),
        ),
        SingleAttemptOrchestrator(
            _gateway(_completion("Finished.")),
            AllowAllPolicy(),
            SequenceToolGateway(),
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == (
        "selected_skill_tools_unavailable"
    )
    assert result.events[-1].event_type is EventType.SESSION_FAILED


def test_failed_research_returns_to_model_and_uses_web_fallback() -> None:
    research = _tool_call(
        "agent.research",
        {
            "objective": "Find market data.",
            "delegation_reason": "Independent multi-source collection is useful.",
        },
        "call_research",
    )
    web = _tool_call("web.fetch", {"url": "https://example.com/market"}, "call_web")
    gateway = _gateway(
        _completion("Delegate the research.", research),
        _completion("The workspace search failed; use the Web.", web),
        _completion("Recovered with external evidence."),
    )

    class FailingResearchGateway(SequenceToolGateway):
        def execute(self, tool_call: ToolCall) -> ToolResult:
            self.calls.append(tool_call)
            if tool_call.name == "agent.research":
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    status=ToolCallStatus.FAILED,
                    output='{"status":"failed","summary":"no workspace evidence"}',
                )
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
                output="market evidence",
            )

    tools = FailingResearchGateway()
    result = HarnessLoop().run(
        HarnessTask(
            title="Recover external research",
            user_input="Find current market data.",
            max_model_calls=3,
            max_tool_calls=2,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert [call.name for call in tools.calls] == ["agent.research", "web.fetch"]
    assert result.run_result.model_calls_used == 3
    assert result.run_result.tool_calls_used == 2
    assert result.attempt_result.metadata["recoverable_tool_failure_count"] == 1
    assert result.attempt_result.metadata["last_failed_tool_name"] == "agent.research"
    assert any(
        message.role is MessageRole.TOOL and "no workspace evidence" in message.content
        for message in gateway.requests[1]
    )

def test_bounded_loop_returns_one_repeated_read_to_model_without_reexecution() -> None:
    first = _tool_call("files.read", {"path": "same.txt"}, "call_one")
    repeated = _tool_call("files.read", {"path": "same.txt"}, "call_two")
    gateway = _gateway(
        _completion("Read it.", first),
        _completion("Read it again.", repeated),
        _completion("Finished from prior evidence."),
    )
    tools = SequenceToolGateway()

    result = HarnessLoop().run(
        HarnessTask(
            title="Repeated task",
            user_input="Inspect the file.",
            max_model_calls=4,
            max_tool_calls=3,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["repeated_read_recovery_count"] == 1
    assert result.run_result.model_calls_used == 3
    assert result.run_result.tool_calls_used == 1
    assert len(tools.calls) == 1


def test_bounded_loop_keeps_observing_repeated_reads_until_threshold() -> None:
    first = _tool_call("files.read", {"path": "same.txt"}, "call_one")
    repeated = _tool_call("files.read", {"path": "same.txt"}, "call_two")
    repeated_again = _tool_call("files.read", {"path": "same.txt"}, "call_three")
    gateway = _gateway(
        _completion("Read it.", first),
        _completion("Read it again.", repeated),
        _completion("Still read it again.", repeated_again),
        _completion("Finished from prior evidence."),
    )
    tools = SequenceToolGateway()

    result = HarnessLoop().run(
        HarnessTask(
            title="Repeated task",
            user_input="Inspect the file.",
            max_model_calls=5,
            max_tool_calls=3,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    # With threshold 3, two repeats (one recovered, one observed) do not
    # hard-stop; the model keeps getting observations to self-correct.
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["repeated_read_recovery_count"] == 1
    assert result.run_result.model_calls_used == 4
    assert result.run_result.tool_calls_used == 1
    assert len(tools.calls) == 1


def test_bounded_loop_stops_when_no_model_call_remains_for_final_answer() -> None:
    tool_call = _tool_call("files.read", {"path": "input.txt"}, "call_read")
    gateway = _gateway(_completion("Read the input.", tool_call))

    result = HarnessLoop().run(
        HarnessTask(
            title="Exhausted task",
            user_input="Read the input.",
            max_model_calls=1,
            max_tool_calls=1,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            SequenceToolGateway(),
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == ("model_call_budget_exhausted")
    assert result.events[-1].event_type is EventType.SESSION_SUSPENDED
    assert result.run_result.stop_reason is HarnessStopReason.MODEL_CALL_BUDGET_EXHAUSTED


def test_final_permitted_model_call_can_still_use_a_tool_before_suspending() -> None:
    first = _tool_call("files.read", {"path": "a.txt"}, "call_a")
    second = _tool_call("files.read", {"path": "b.txt"}, "call_b")
    gateway = _gateway(
        _completion("Read the first input.", first),
        _completion("Read the second input too.", second),
    )
    tools = SequenceToolGateway()

    result = HarnessLoop().run(
        HarnessTask(
            title="Use the full explicit model budget",
            user_input="Read both inputs.",
            max_model_calls=2,
            max_tool_calls=2,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "model_call_budget_exhausted"
    assert result.run_result.model_calls_used == 2
    assert result.run_result.tool_calls_used == 2
    assert [call.provider_call_id for call in tools.calls] == ["call_a", "call_b"]


def _gateway(*completions: ModelCompletion) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=tuple(ScriptedModelResponse(completion=completion) for completion in completions)
    )


def _completion(content: str, tool_call: ToolCall | None = None) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=(tool_call,) if tool_call is not None else (),
    )


def _tool_call(name: str, arguments: dict[str, object], call_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=NOW,
        provider_call_id=call_id,
    )
