"""AG-UI orchestration state projection tests (plan 14.2 shape)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.identifiers import TaskId
from agent_core.domain.subagents import CompletionGateReceipt
from agent_integrations.ag_ui.orchestration_state import (
    AgUiNodeFacts,
    OrchestrationStateInput,
    project_orchestration_state,
)
from agent_orchestration.domain.orchestration import (
    OrchestrationDependency,
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
    OrchestrationRunStatus,
    snapshot_from_proposal,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation


def _node(key: str, role: str = "researcher") -> OrchestrationNodeProposal:
    return OrchestrationNodeProposal(
        node_key=key,
        objective=key,
        preferred_agent_role=role,
        required_capabilities=frozenset(capability_set(["evidence.read"])),
        max_model_tokens=100,
        max_model_calls=2,
        max_tool_calls=3,
        max_runtime_seconds=60,
    )


def _snapshot() -> object:
    proposal = OrchestrationPlanProposal(
        objective="Analyze",
        nodes=(_node("research-a"), _node("research-b")),
        dependencies=(OrchestrationDependency(from_node="research-a", to_node="research-b"),),
        max_parallelism=1,
        synthesis_instruction="Merge",
    )
    return snapshot_from_proposal(
        proposal,
        run_ref="run-agui",
        parent_task_id=TaskId(uuid4()),
        parent_binding_digest="a" * 64,
        reserved_budget=BudgetReservation(
            model_tokens=10_000, tool_calls=50, runtime_seconds=600
        ),
    )


def _gate(passed: bool = True) -> CompletionGateReceipt:
    return CompletionGateReceipt(
        gate_name="research.evidence",
        passed=passed,
        reason_code="evidence_satisfied" if passed else "no_evidence_collected",
        evaluated_at=datetime.now(UTC),
    )


class TestShape:
    def test_projection_matches_the_plan_142_structure(self) -> None:
        snapshot = _snapshot()
        state = OrchestrationStateInput(
            snapshot=snapshot,  # type: ignore[arg-type]
            run_status=OrchestrationRunStatus.RUNNING,
            node_facts={
                "research-a": AgUiNodeFacts(
                    status="completed",
                    activity=None,
                    elapsed_seconds=42,
                    model_calls_used=2,
                    tool_calls_used=3,
                    evidence_count=2,
                    model_tokens_used=800,
                    tool_budget_used=3,
                    gate=_gate(True),
                ),
                "research-b": AgUiNodeFacts(status="running", activity="Reading evidence"),
            },
        )
        projected = project_orchestration_state(state)
        orch = projected["orchestration"]
        assert orch["runId"] == "run-agui"
        assert orch["status"] == "running"
        assert orch["planRevision"] == 1
        assert orch["planDigest"] == snapshot.plan_digest  # type: ignore[attr-defined]
        nodes = orch["nodes"]
        assert set(nodes) == {"research-a", "research-b"}
        first = nodes["research-a"]
        assert first["role"] == "researcher"
        assert first["status"] == "completed"
        assert first["elapsedSeconds"] == 42
        assert first["evidenceCount"] == 2
        assert first["gate"] == {
            "gateName": "research.evidence",
            "passed": True,
            "reasonCode": "evidence_satisfied",
        }
        second = nodes["research-b"]
        assert second["status"] == "running"
        assert second["activity"] == "Reading evidence"
        assert second["gate"] is None

    def test_projection_serializes_to_json_without_secrets(self) -> None:
        snapshot = _snapshot()
        state = OrchestrationStateInput(
            snapshot=snapshot,  # type: ignore[arg-type]
            run_status=OrchestrationRunStatus.WAITING,
            node_facts={},
        )
        encoded = json.dumps(project_orchestration_state(state))
        assert "orchestration" in encoded
        assert "secret" not in encoded and "token" not in encoded

    def test_missing_facts_project_as_blocked(self) -> None:
        snapshot = _snapshot()
        state = OrchestrationStateInput(
            snapshot=snapshot,  # type: ignore[arg-type]
            run_status=OrchestrationRunStatus.MATERIALIZING,
            node_facts={},
        )
        projected = project_orchestration_state(state)
        nodes = projected["orchestration"]["nodes"]
        assert all(node["status"] == "blocked" for node in nodes.values())
        assert all(node["childTaskId"] is None for node in nodes.values())


class TestGuards:
    def test_passed_gate_on_non_completed_node_is_rejected(self) -> None:
        with pytest.raises(Exception, match="passed gate"):
            AgUiNodeFacts(status="running", gate=_gate(True))

    def test_failed_gate_on_running_node_is_acceptable_input(self) -> None:
        facts = AgUiNodeFacts(status="failed", gate=_gate(False))
        assert facts.gate is not None and not facts.gate.passed
