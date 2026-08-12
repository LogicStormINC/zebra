from datetime import UTC, datetime

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.messages import MessageRole
from agent_core.harness.completion_blocking import append_missing_evidence_observation


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

    append_missing_evidence_observation(
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
