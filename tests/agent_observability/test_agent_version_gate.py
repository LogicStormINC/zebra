"""AGENT-DEF-EVAL-01: Agent Version publication gate tests."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
)
from agent_observability.agent_versions import (
    REQUIRED_PUBLICATION_CONDITIONS,
    AgentVersionPublicationCondition,
    AgentVersionPublicationGate,
    AgentVersionPublicationGateService,
    AgentVersionPublicationGateStatus,
)

CREATED = datetime(2026, 8, 16, 13, 0, tzinfo=UTC)
DIGEST = sha256(b"version-content").hexdigest()
DEFINITION_ID = AgentDefinitionId(UUID("50000000-0000-0000-0000-000000000001"))
VERSION_ID = AgentDefinitionVersionId(UUID("60000000-0000-0000-0000-000000000001"))


def _conditions(**overrides: bool) -> tuple[AgentVersionPublicationCondition, ...]:
    defaults: dict[str, bool] = {
        "regression": True,
        "safety": True,
        "recovery": True,
        "cost": True,
        "latency": True,
    }
    defaults.update(overrides)
    return tuple(
        AgentVersionPublicationCondition(
            name=name,
            passed=passed,
            reason="deterministic eval evidence passed",
            evidence_ref=f"evals/agent-definitions/{name}.json",
        )
        for name, passed in defaults.items()
    )


def _service() -> AgentVersionPublicationGateService:
    return AgentVersionPublicationGateService()


def test_gate_passes_with_complete_evidence() -> None:
    gate = _service().evaluate(
        definition_id=DEFINITION_ID,
        version_id=VERSION_ID,
        definition_digest=DIGEST,
        policy_version="policies/evals/release@v5",
        conditions=_conditions(),
        evaluator_actor="eval-bot",
        evaluated_at=CREATED,
    )
    assert gate.passed is True
    assert gate.status is AgentVersionPublicationGateStatus.PASSED
    assert gate.definition_digest == DIGEST
    assert len(gate.conditions) == len(REQUIRED_PUBLICATION_CONDITIONS)


def test_gate_is_pending_without_required_evidence() -> None:
    gate = _service().evaluate(
        definition_id=DEFINITION_ID,
        version_id=VERSION_ID,
        definition_digest=DIGEST,
        policy_version="policies/evals/release@v5",
        conditions=_conditions(regression=False)[:2],
        evaluator_actor="eval-bot",
        evaluated_at=CREATED,
    )
    assert gate.status is AgentVersionPublicationGateStatus.PENDING
    assert gate.passed is False


def test_gate_fails_with_explicit_reasons() -> None:
    gate = _service().evaluate(
        definition_id=DEFINITION_ID,
        version_id=VERSION_ID,
        definition_digest=DIGEST,
        policy_version="policies/evals/release@v5",
        conditions=_conditions(safety=False, cost=False),
        evaluator_actor="eval-bot",
        evaluated_at=CREATED,
    )
    assert gate.status is AgentVersionPublicationGateStatus.FAILED
    failed = {
        condition.name
        for condition in gate.conditions
        if not condition.passed
    }
    assert failed == {"safety", "cost"}


def test_gate_pins_exact_version_identity() -> None:
    gate = _service().evaluate(
        definition_id=DEFINITION_ID,
        version_id=VERSION_ID,
        definition_digest=DIGEST,
        policy_version="policies/evals/release@v5",
        conditions=_conditions(),
        evaluator_actor="eval-bot",
        evaluated_at=CREATED,
    )
    assert gate.version_id == VERSION_ID
    assert gate.definition_digest == DIGEST
    assert gate.llm_judge_supplemental is False


def test_gate_rejects_tampered_digest() -> None:
    with pytest.raises(ValueError):
        AgentVersionPublicationGate(
            definition_id=DEFINITION_ID,
            version_id=VERSION_ID,
            definition_digest="not-a-digest",
            policy_version="policies/evals/release@v5",
            status=AgentVersionPublicationGateStatus.PASSED,
            conditions=_conditions(),
            required_condition_names=REQUIRED_PUBLICATION_CONDITIONS,
            evaluator_actor="eval-bot",
            evaluated_at=CREATED,
        )
