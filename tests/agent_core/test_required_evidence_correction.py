from datetime import UTC, datetime

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelInvocationPolicy,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import (
    HarnessAttemptOutcome,
    HarnessLoop,
    HarnessModelStep,
    HarnessTask,
    SingleAttemptOrchestrator,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)
PRODUCER = ModelToolDefinition(
    name="evidence.lookup",
    description="Read trusted evidence.",
    parameters={"type": "object", "properties": {}},
)
IRRELEVANT = ModelToolDefinition(
    name="irrelevant.lookup",
    description="Read unrelated data.",
    parameters={"type": "object", "properties": {}},
)


class Gateway:
    def __init__(self) -> None:
        self.requests: list[tuple[tuple[str, ...], ModelInvocationPolicy | None]] = []

    def complete(self, messages, *, tools=(), media_inputs=()):
        self.requests.append((tuple(tool.name for tool in tools), None))
        if len(self.requests) == 1:
            return _completion("Ready without evidence.")
        return _completion("Ready with evidence.")

    def complete_with_policy(
        self, messages, *, tools=(), media_inputs=(), invocation_policy
    ):
        self.requests.append(
            (tuple(tool.name for tool in tools), invocation_policy)
        )
        return _completion(
            "Collecting evidence.",
            ToolCall(
                tool_call_id=new_tool_call_id(),
                name="evidence.lookup",
                created_at=NOW,
            ),
        )


class Policy:
    def evaluate_tool_call(self, _tool_call):
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="allowed",
            policy_profile="test",
        )


class Tools:
    def execute(self, tool_call):
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="trusted fact",
            metadata={"typed_evidence": ["external.fact.confirmed"]},
        )


def test_missing_typed_evidence_forces_one_producer_then_restores_catalog() -> None:
    gateway = Gateway()
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="required_external_fact",
                    typed_evidence=("external.fact.confirmed",),
                ),
            )
        ),
    )

    result = HarnessLoop().run(
        HarnessTask(
            title="Evidence correction",
            user_input="Answer from trusted facts.",
            max_model_calls=4,
            agent_definition=definition,
            trusted_evidence_tools={
                "evidence.lookup": ("external.fact.confirmed",)
            },
        ),
        SingleAttemptOrchestrator(
            gateway,
            Policy(),
            Tools(),
            model_step=HarnessModelStep(available_tools=(PRODUCER, IRRELEVANT)),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert gateway.requests[0] == (("evidence.lookup", "irrelevant.lookup"), None)
    assert gateway.requests[1][0] == ("evidence.lookup",)
    assert gateway.requests[1][1].tool_choice is ModelToolChoice.REQUIRED
    assert gateway.requests[2] == (("evidence.lookup", "irrelevant.lookup"), None)


def test_required_evidence_producer_budget_shortage_fails_closed() -> None:
    gateway = Gateway()
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="required_external_fact",
                    typed_evidence=("external.fact.confirmed",),
                ),
            )
        ),
    )

    result = HarnessLoop().run(
        HarnessTask(
            title="Bounded evidence correction",
            user_input="Answer from trusted facts.",
            max_model_calls=2,
            agent_definition=definition,
            trusted_evidence_tools={
                "evidence.lookup": ("external.fact.confirmed",)
            },
        ),
        SingleAttemptOrchestrator(
            gateway,
            Policy(),
            Tools(),
            model_step=HarnessModelStep(available_tools=(PRODUCER, IRRELEVANT)),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )

    assert result.attempt_result.outcome is HarnessAttemptOutcome.FAILED
    assert result.attempt_result.metadata["stop_reason"] == "completion_evidence_missing"
    assert len(gateway.requests) == 1


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
