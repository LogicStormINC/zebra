"""AG-UI orchestration state projection (ORCH-AGUI-01, plan section 14.2).

A pure projection from durable orchestration facts to the Host-visible
state object: task graph, per-node child status/activity/elapsed, budget
usage, evidence counts and gate verdicts. No secrets, no raw payloads —
the same rule as every AG-UI projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from agent_core.domain.subagents import CompletionGateReceipt
from agent_orchestration.domain.orchestration import (
    OrchestrationPlanSnapshot,
    OrchestrationRunStatus,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgUiNodeFacts(BaseModel):
    """Durable facts for one node, gathered by the projection reader."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    activity: str | None = Field(default=None, max_length=256)
    elapsed_seconds: int = Field(default=0, ge=0)
    model_calls_used: int = Field(default=0, ge=0)
    tool_calls_used: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    model_tokens_used: int = Field(default=0, ge=0)
    tool_budget_used: int = Field(default=0, ge=0)
    gate: CompletionGateReceipt | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.gate is not None and self.gate.passed and self.status != "completed":
            raise ValueError("a passed gate must accompany a completed node")
        return self


@dataclass(frozen=True)
class OrchestrationStateInput:
    """Everything the projection needs from the v27 store and ledgers."""

    snapshot: OrchestrationPlanSnapshot
    run_status: OrchestrationRunStatus
    node_facts: dict[str, AgUiNodeFacts]


def project_orchestration_state(state: OrchestrationStateInput) -> dict[str, object]:
    """Project the plan-14.2 orchestration state object."""

    nodes: dict[str, dict[str, object]] = {}
    for node in state.snapshot.nodes:
        facts = state.node_facts.get(
            node.node_key,
            AgUiNodeFacts(status="blocked"),
        )
        nodes[node.node_key] = {
            "childTaskId": str(node.child_task_id) if node.child_task_id else None,
            "role": node.proposal.preferred_agent_role,
            "status": facts.status,
            "activity": facts.activity,
            "elapsedSeconds": facts.elapsed_seconds,
            "modelCallsUsed": facts.model_calls_used,
            "toolCallsUsed": facts.tool_calls_used,
            "evidenceCount": facts.evidence_count,
            "budget": {
                "modelTokensUsed": facts.model_tokens_used,
                "toolCallsUsed": facts.tool_budget_used,
            },
            "gate": _gate_view(facts.gate),
        }
    return {
        "orchestration": {
            "runId": state.snapshot.run_ref,
            "status": state.run_status.value,
            "planRevision": state.snapshot.plan_revision,
            "planDigest": state.snapshot.plan_digest,
            "completionStrategy": state.snapshot.completion_strategy,
            "nodes": nodes,
        }
    }


def _gate_view(gate: CompletionGateReceipt | None) -> dict[str, object] | None:
    if gate is None:
        return None
    return {
        "gateName": gate.gate_name,
        "passed": gate.passed,
        "reasonCode": gate.reason_code,
    }
