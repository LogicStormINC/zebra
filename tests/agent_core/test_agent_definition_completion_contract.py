from datetime import UTC, datetime

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionContext,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
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

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
TOOLS = (
    ModelToolDefinition(
        name="evidence.lookup",
        description="Look up one typed evidence item.",
        parameters={"type": "object", "properties": {}},
    ),
    ModelToolDefinition(
        name="evidence.validate",
        description="Validate the current typed evidence.",
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


class ScriptedGateway:
    def __init__(self, responses: tuple[ModelCompletion, ...]) -> None:
        self.responses = responses
        self.cursor = 0
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
        response = self.responses[self.cursor]
        self.cursor += 1
        return response


class EvidenceTools:
    def execute(self, tool_call: ToolCall) -> ToolResult:
        metadata: dict[str, object] = {}
        if tool_call.name == "evidence.lookup":
            metadata["typed_evidence"] = ["lookup.ready"]
        else:
            metadata["tool_tags"] = ["validator"]
            metadata["validator_outcome"] = "passed"
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=tool_call.name,
            metadata=metadata,
        )


def test_missing_typed_evidence_gets_one_bounded_observation() -> None:
    definition = _definition()
    gateway = ScriptedGateway(
        (
            _completion("The answer is ready."),
            _completion("I need to gather evidence.", _call("evidence.lookup")),
            _completion("Validate the evidence.", _call("evidence.validate")),
            _completion("The typed evidence is ready."),
        )
    )

    result = _run(gateway, EvidenceTools(), definition)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.model_calls_used == 4
    assert any(
        message.role is MessageRole.SYSTEM
        and "missing_completion_evidence" in message.content
        for message in gateway.requests[1]
    )


def test_required_evidence_can_arrive_in_any_tool_order() -> None:
    definition = _definition()
    first = _call("evidence.validate")
    second = _call("evidence.lookup")
    gateway = ScriptedGateway(
        (
            _completion("Validate first.", first),
            _completion("Look up second.", second),
            _completion("All required evidence passed."),
        )
    )

    result = _run(gateway, EvidenceTools(), definition, max_model_calls=3)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata["completion_evidence_satisfied"] is True


def test_repeated_missing_evidence_suspends_without_looping() -> None:
    definition = _definition()
    gateway = ScriptedGateway(
        (_completion("No typed evidence."), _completion("Still no typed evidence."))
    )

    result = _run(gateway, EvidenceTools(), definition, max_model_calls=2)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.attempt_result.metadata["stop_reason"] == "completion_evidence_missing"
    assert len(gateway.requests) == 2
    assert sum(
        "missing_completion_evidence" in message.content
        for request in gateway.requests
        for message in request
        if message.role is MessageRole.SYSTEM
    ) == 1


def test_no_definition_keeps_legacy_no_tool_completion() -> None:
    gateway = ScriptedGateway((_completion("Direct answer."),))

    result = _run(gateway, EvidenceTools(), None)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.run_result.model_calls_used == 1


def test_resolved_definition_context_is_a_system_message() -> None:
    messages = HarnessModelStep().build_initial_messages(
        HarnessTask(
            title="System context",
            user_input="Use the configured context.",
            agent_definition=AgentDefinition(agent_id="agent-neutral", version="1.0.0"),
            agent_context=AgentDefinitionContext(
                agent_id="agent-neutral",
                version="1.0.0",
                system_prompt="Trusted system instruction.",
            ),
        ),
        created_at=NOW,
    )

    assert messages[0].role is MessageRole.SYSTEM
    assert "Trusted system instruction." in messages[0].content


def test_missing_required_model_capability_fails_closed() -> None:
    gateway = ScriptedGateway((_completion("must not run"),))
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        required_model_capabilities=("image",),
    )

    result = _run(gateway, EvidenceTools(), definition)

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == (
        "agent_definition_model_capability_missing"
    )
    assert gateway.requests == []


def _definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="agent-neutral",
        version="2026.08.02",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="lookup",
                    typed_evidence=("lookup.ready",),
                ),
                CompletionEvidenceRequirement(
                    evidence_id="validation",
                    validator_outcome="passed",
                ),
            )
        ),
    )


def _run(
    gateway: ScriptedGateway,
    tools: EvidenceTools,
    definition: AgentDefinition | None,
    *,
    max_model_calls: int | None = None,
):
    return HarnessLoop().run(
        HarnessTask(
            title="Neutral evidence task",
            user_input="Collect the required typed evidence.",
            max_model_calls=max_model_calls,
            agent_definition=definition,
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


def _call(name: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        created_at=NOW,
    )
