from datetime import UTC, datetime

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.messages import MessageRole
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelInvocationPolicy,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_core.harness.completion_blocking import append_missing_evidence_observation
from agent_core.harness.model_step import HarnessModelStep


def test_missing_evidence_observation_names_its_advertised_trusted_tool() -> None:
    messages = []
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

    producers = append_missing_evidence_observation(
        messages,
        missing=("required_external_fact",),
        open_plan_steps=(),
        definition=definition,
        trusted_evidence_tools={
            "evidence.lookup": ("external.fact.confirmed",),
            "irrelevant.lookup": ("other.fact",),
        },
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert messages[0].role is MessageRole.SYSTEM
    assert "external.fact.confirmed" in messages[0].content
    assert "evidence.lookup" in messages[0].content
    assert "irrelevant.lookup" not in messages[0].content
    assert producers == ("evidence.lookup",)


def test_evidence_correction_requires_only_the_matching_producer() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.tools = ()
            self.policy = None

        def complete(self, messages, *, tools=(), media_inputs=()):
            raise AssertionError("evidence correction must use the policy-aware port")

        def complete_with_policy(
            self, messages, *, tools=(), media_inputs=(), invocation_policy
        ):
            self.tools = tools
            self.policy = invocation_policy
            return ModelCompletion(
                assistant_message=messages[-1].model_copy(
                    update={"role": MessageRole.ASSISTANT, "content": "Calling evidence."}
                )
            )

    producer = ModelToolDefinition(
        name="evidence.lookup",
        description="Read trusted evidence.",
        parameters={"type": "object", "properties": {}},
    )
    irrelevant = ModelToolDefinition(
        name="irrelevant.lookup",
        description="Read unrelated data.",
        parameters={"type": "object", "properties": {}},
    )
    gateway = Gateway()
    messages = []
    append_missing_evidence_observation(
        messages,
        missing=("required_external_fact",),
        open_plan_steps=(),
        definition=AgentDefinition(
            agent_id="agent-neutral",
            version="1.0.0",
        ),
        trusted_evidence_tools={},
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    HarnessModelStep(available_tools=(producer, irrelevant)).request_completion(
        messages,
        gateway,
        allow_tools=True,
        required_tool_names=("evidence.lookup",),
        invocation_policy=ModelInvocationPolicy(tool_choice=ModelToolChoice.REQUIRED),
    )

    assert tuple(tool.name for tool in gateway.tools) == ("evidence.lookup",)
    assert gateway.policy.tool_choice is ModelToolChoice.REQUIRED
