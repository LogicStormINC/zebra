from datetime import UTC, datetime

from agent_context import LocalContextCompiler
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


class FinalInstructionAwareGateway:
    def __init__(self, responses: tuple[ModelCompletion, ...]) -> None:
        self._responses = responses
        self._cursor = 0
        self.requests: list[tuple[SessionMessage, ...]] = []
        self.tool_requests: list[tuple[ModelToolDefinition, ...]] = []

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        self.requests.append(tuple(messages))
        self.tool_requests.append(tools)
        if tools:
            response = self._responses[self._cursor]
            self._cursor += 1
            return response
        if (
            messages[-1].role is MessageRole.USER
            and messages[-1].content.startswith("The tool budget is complete.")
            and "Do not request or invoke another tool." in messages[-1].content
        ):
            assert any("SUCCESS-OCR-LONG-TAIL" in message.content for message in messages)
            return _completion("CORRECT-FINAL-FROM-SUCCESS-OCR-LONG-TAIL")
        return _completion(
            "<｜｜DSML｜｜tool_calls>\n"
            "<｜｜DSML｜｜invoke name=\"web__search\">\n"
            "</｜｜DSML｜｜invoke>\n"
            "</｜｜DSML｜｜tool_calls>"
        )


class RecoveryFirstModelStep(HarnessModelStep):
    def __init__(self, *, recover: bool) -> None:
        super().__init__(available_tools=TOOLS)
        self._recover = recover
        self.calls: list[str] = []

    def recover_conversation(self, messages, model_gateway):
        del messages, model_gateway
        self.calls.append("recover")
        return self._recover

    def prepare_conversation(self, messages, model_gateway, *, allow_tools, user_goal, created_at):
        del messages, model_gateway, user_goal, created_at
        self.calls.append(f"prepare:{allow_tools}")
        return None


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


def test_tool_disabled_budget_final_compiles_before_recovering() -> None:
    tool_call = _tool_call("files.read", {"path": "input.txt"}, "call_read")
    gateway = _gateway(
        _completion("Read the input.", tool_call),
        _completion("Final answer from recovered evidence."),
    )
    model_step = RecoveryFirstModelStep(recover=True)

    result = HarnessLoop().run(
        HarnessTask(
            title="Budget terminal task",
            user_input="Read the input.",
            max_model_calls=2,
            max_tool_calls=1,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            SequenceToolGateway(),
            model_step=model_step,
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert model_step.calls == ["prepare:True", "prepare:False", "recover"]


def test_tool_result_final_uses_the_same_compile_then_recover_entrypoint() -> None:
    tool_call = _tool_call("files.read", {"path": "input.txt"}, "call_read")
    model_step = RecoveryFirstModelStep(recover=False)

    completion = model_step.request_tool_result_completion(
        HarnessTask(title="Single result", user_input="Read the input."),
        _gateway(_completion("Final answer from the result.")),
        initial_completion=_completion("Read the input.", tool_call),
        tool_call=tool_call,
        tool_result=ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="evidence",
        ),
        created_at=NOW,
    )

    assert completion.assistant_message.content == "Final answer from the result."
    assert model_step.calls == ["prepare:False", "recover"]


def test_budget_final_recovers_the_latest_successful_operation_evidence() -> None:
    operation_key = "opaque-image-operation"
    timeout = _tool_call(
        "mcp.minimax.understand_image",
        {"image_source": "receipts/statement.png", "prompt": "Read totals."},
        "image-timeout",
    )
    success = _tool_call(
        "mcp.minimax.understand_image",
        {"image_source": "receipts/statement.png", "prompt": "Read every row."},
        "image-success",
    )
    others = tuple(
        _tool_call("files.read", {"path": f"other-{index}.txt"}, f"other-{index}")
        for index in range(4)
    )

    class RetriedEvidenceTools:
        def execute(self, tool_call: ToolCall) -> ToolResult:
            if tool_call.provider_call_id == "image-timeout":
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    status=ToolCallStatus.FAILED,
                    output="OLD-TIMEOUT-WITHOUT-ERROR-MARKERS",
                    metadata={"operation_key": operation_key},
                )
            if tool_call.provider_call_id == "image-success":
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    status=ToolCallStatus.EXECUTED,
                    output="SUCCESS-OCR-LONG-TAIL " + "evidence " * 400,
                    metadata={"operation_key": operation_key},
                )
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
                output="other evidence " * 400,
            )

    gateway = _gateway(
        _completion("Read the image.", timeout),
        _completion("Retry with a fuller prompt.", success),
        *(_completion("Read other evidence.", call) for call in others),
        _completion("Final answer from SUCCESS-OCR-LONG-TAIL."),
    )
    result = HarnessLoop().run(
        HarnessTask(
            title="Compacted retry",
            user_input="Read the image and summarize it.",
            max_model_calls=7,
            max_tool_calls=6,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            RetriedEvidenceTools(),
            model_step=HarnessModelStep(
                available_tools=TOOLS,
                conversation_compactor=LocalContextCompiler(),
                conversation_token_budget=600,
            ),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    final_context = "\n".join(message.content for message in gateway.requests[-1])
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert gateway.tool_requests[-1] == ()
    assert "SUCCESS-OCR-LONG-TAIL" in final_context
    assert "OLD-TIMEOUT" not in final_context
    assert sum(
        event.event_type is EventType.CONTEXT_COMPACTED for event in result.events
    ) >= 2


def test_voluntary_tool_loop_final_is_replaced_by_one_recovered_final() -> None:
    operation_key = "opaque-operation"
    timeout = _tool_call("mcp.fixture.lookup", {"resource": "first"}, "old-call")
    success = _tool_call("mcp.fixture.lookup", {"resource": "second"}, "success-call")
    others = tuple(
        _tool_call("files.read", {"path": f"other-{index}.txt"}, f"other-{index}")
        for index in range(4)
    )

    class RetriedEvidenceTools:
        def execute(self, tool_call: ToolCall) -> ToolResult:
            if tool_call.provider_call_id == "old-call":
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    status=ToolCallStatus.FAILED,
                    output="OLD-TIMEOUT",
                    metadata={"operation_key": operation_key},
                )
            if tool_call.provider_call_id == "success-call":
                return ToolResult(
                    tool_call_id=tool_call.tool_call_id,
                    status=ToolCallStatus.EXECUTED,
                    output="SUCCESS-OCR-LONG-TAIL " + "evidence " * 400,
                    metadata={"operation_key": operation_key},
                )
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
                output=f"other evidence {tool_call.provider_call_id} " * 400,
            )

    gateway = FinalInstructionAwareGateway(
        (
            _completion("Read the first result.", timeout),
            _completion("Retry the result.", success),
            *(_completion("Read supporting evidence.", call) for call in others),
            _completion("WRONG-PROVISIONAL-FINAL"),
        )
    )
    result = HarnessLoop().run(
        HarnessTask(
            title="Recover a voluntary final",
            user_input="Use the completed evidence.",
            max_model_calls=8,
            max_tool_calls=7,
        ),
        SingleAttemptOrchestrator(
            gateway,
            AllowAllPolicy(),
            RetriedEvidenceTools(),
            model_step=HarnessModelStep(
                available_tools=TOOLS,
                conversation_compactor=LocalContextCompiler(),
                conversation_token_budget=600,
            ),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    final_context = "\n".join(message.content for message in gateway.requests[-1])
    model_events = [
        event
        for event in result.events
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
    ]
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == (
        "CORRECT-FINAL-FROM-SUCCESS-OCR-LONG-TAIL"
    )
    assert result.run_result.model_calls_used == 8
    assert gateway.tool_requests[-1] == ()
    assert gateway.tool_requests.count(()) == 1
    assert "SUCCESS-OCR-LONG-TAIL" in final_context
    assert "OLD-TIMEOUT" not in final_context
    assert sum(
        message.content.startswith("The tool budget is complete.")
        for message in gateway.requests[-1]
    ) == 1
    assert model_events[-2].payload["response_stage"] == "tool_loop"
    assert model_events[-1].payload["response_stage"] == "final"
    assert not any(
        message.metadata.get("tool_loop_no_progress") is True
        for message in gateway.requests[-1]
    )


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
