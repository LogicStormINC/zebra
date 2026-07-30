from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)

NOW = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
VALIDATOR_NAME = "quality.validate"
TOOLS = (
    ModelToolDefinition(
        name=VALIDATOR_NAME,
        description="Validate a structured candidate.",
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


class ValidatorGateway:
    def __init__(self, *passed: bool) -> None:
        self._passed = iter(passed)
        self.calls: list[ToolCall] = []

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output='{"validator_result":{"passed":false,"issues":[{"code":"mismatch"}]}}',
            metadata={"validator_result": {"passed": next(self._passed)}},
        )


class FailedValidatorGateway(ValidatorGateway):
    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls.append(tool_call)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            output="validator unavailable",
        )


def test_failed_validator_gets_one_tool_disabled_correction() -> None:
    call = _call("first")
    model = _model(_completion("Validate the draft.", call), _completion("Corrected final."))
    tools = ValidatorGateway(False)

    result = _run(model, tools, max_model_calls=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "Corrected final."
    assert result.attempt_result.metadata["validator_correction_attempted"] is True
    assert tools.calls == [call]
    assert model.tool_requests == (TOOLS, ())
    assert any(
        message.metadata.get("validator_correction") is True
        for message in model.requests[-1]
    )


def test_second_validator_is_not_executed() -> None:
    first = _call("first")
    second = _call("second")
    model = _model(
        _completion("Validate once.", first),
        _completion("Validate again.", second),
    )
    tools = ValidatorGateway(True)

    result = _run(model, tools, max_model_calls=3)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "validator_call_limit"
    assert tools.calls == [first]


def test_second_validator_is_not_executed_after_a_failed_first_call() -> None:
    first = _call("first")
    second = _call("second")
    model = _model(
        _completion("Validate once.", first),
        _completion("Try the validator again.", second),
    )
    tools = FailedValidatorGateway()

    result = _run(model, tools, max_model_calls=3)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "validator_call_limit"
    assert tools.calls == [first]


def _run(
    model: ScriptedModelGateway,
    tools: ValidatorGateway,
    *,
    max_model_calls: int,
):
    return HarnessLoop().run(
        HarnessTask(
            title="Validator correction",
            user_input="Produce a consistent report.",
            max_model_calls=max_model_calls,
        ),
        SingleAttemptOrchestrator(
            model,
            AllowAllPolicy(),
            tools,
            model_step=HarnessModelStep(available_tools=TOOLS),
            synthesize_tool_results=True,
            validator_tool_names=frozenset({VALIDATOR_NAME}),
        ).run,
        created_at=NOW,
    )


def _model(*completions: ModelCompletion) -> ScriptedModelGateway:
    return ScriptedModelGateway(
        responses=tuple(ScriptedModelResponse(completion=value) for value in completions)
    )


def _completion(content: str, *tool_calls: ToolCall) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=NOW,
        ),
        tool_calls=tool_calls,
    )


def _call(provider_call_id: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=VALIDATOR_NAME,
        arguments={"report": {}},
        created_at=NOW,
        provider_call_id=provider_call_id,
    )
