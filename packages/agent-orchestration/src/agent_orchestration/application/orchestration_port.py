"""Orchestration runtime port consumed by Agent Layer tools (CA-P7-02A).

The Orchestrator AgentDefinition holds no bypass privileges: every
orchestration tool is an Agent Layer application call and reaches storage
only through this port's runtime implementation. The port keeps tools
testable without a database and keeps the worker loop (CA-P7-02B) as the
single writer of orchestration state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_orchestration.domain.orchestration import (
    OrchestrationPlanProposal,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation


class OrchestrationToolError(RuntimeError):
    """One typed tool-facing failure; never leaks storage details."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class PlanProposalReceipt:
    """Public facts of an accepted plan — coordinates only, no storage paths."""

    run_ref: str
    plan_revision: int
    node_keys: tuple[str, ...]
    reserved_budget: BudgetReservation


@dataclass(frozen=True)
class TaskRequestReceipt:
    """Public facts of one dispatched node."""

    run_ref: str
    node_key: str
    child_task_id: str


class OrchestrationRuntimePort(Protocol):
    """The Agent Layer surface for the two minimal orchestration tools."""

    def propose_plan(
        self,
        proposal: OrchestrationPlanProposal,
        *,
        parent_task_id: str,
        parent_binding_digest: str,
        parent_remaining_budget: BudgetReservation,
        parent_capabilities: frozenset[str],
        write_capabilities: frozenset[str],
    ) -> PlanProposalReceipt:
        """Validate and freeze one proposal into a run; typed failures only."""

    def request_task(self, *, run_ref: str, node_key: str) -> TaskRequestReceipt:
        """Dispatch one ready node of a run; the worker loop owns scheduling."""
