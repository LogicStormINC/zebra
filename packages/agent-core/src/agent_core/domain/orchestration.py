"""Orchestration contracts: plans, nodes, dependencies, run states.

ORCH-CONTRACT-01 (plan sections 6.4-6.6, 12): the Orchestrator Agent may
only PROPOSE plans; the Control Plane validates and freezes them into
immutable snapshots. Run and Node state machines are explicit and
deterministic; replans append new revisions without rewriting history.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.agent_capabilities import (
    Capability,
    capability_set,
)
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_core.domain.orchestration_budget import BudgetReservation

MAX_NODES = 32
MAX_TEXT = 2048
FIRST_REVISION = 1


class OrchestrationRunStatus(StrEnum):
    """Plan section 12.1 run states."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    MATERIALIZING = "materializing"
    RUNNING = "running"
    WAITING = "waiting"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"


class OrchestrationNodeStatus(StrEnum):
    """Plan section 12.2 node states."""

    BLOCKED = "blocked"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CHILDREN = "waiting_children"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    UNCERTAIN = "uncertain"


NODE_TERMINAL_STATUSES = frozenset(
    {
        OrchestrationNodeStatus.COMPLETED,
        OrchestrationNodeStatus.FAILED,
        OrchestrationNodeStatus.CANCELLED,
        OrchestrationNodeStatus.SKIPPED,
        OrchestrationNodeStatus.UNCERTAIN,
    }
)


RUN_TERMINAL_STATUSES = frozenset(
    {
        OrchestrationRunStatus.COMPLETED,
        OrchestrationRunStatus.FAILED,
        OrchestrationRunStatus.CANCELLED,
    }
)

RUN_TRANSITIONS: dict[OrchestrationRunStatus, frozenset[OrchestrationRunStatus]] = {
    OrchestrationRunStatus.PROPOSED: frozenset(
        {OrchestrationRunStatus.VALIDATED, OrchestrationRunStatus.FAILED}
    ),
    OrchestrationRunStatus.VALIDATED: frozenset(
        {OrchestrationRunStatus.MATERIALIZING, OrchestrationRunStatus.FAILED}
    ),
    OrchestrationRunStatus.MATERIALIZING: frozenset(
        {OrchestrationRunStatus.RUNNING, OrchestrationRunStatus.FAILED}
    ),
    OrchestrationRunStatus.RUNNING: frozenset(
        {
            OrchestrationRunStatus.WAITING,
            OrchestrationRunStatus.SYNTHESIZING,
            OrchestrationRunStatus.SUSPENDED,
            OrchestrationRunStatus.BLOCKED,
            OrchestrationRunStatus.UNCERTAIN,
            OrchestrationRunStatus.FAILED,
            OrchestrationRunStatus.CANCELLED,
        }
    ),
    OrchestrationRunStatus.WAITING: frozenset(
        {
            OrchestrationRunStatus.RUNNING,
            OrchestrationRunStatus.SYNTHESIZING,
            OrchestrationRunStatus.BLOCKED,
            OrchestrationRunStatus.UNCERTAIN,
            OrchestrationRunStatus.FAILED,
            OrchestrationRunStatus.CANCELLED,
        }
    ),
    OrchestrationRunStatus.SYNTHESIZING: frozenset(
        {
            OrchestrationRunStatus.COMPLETED,
            OrchestrationRunStatus.FAILED,
            OrchestrationRunStatus.CANCELLED,
        }
    ),
    OrchestrationRunStatus.SUSPENDED: frozenset(
        {OrchestrationRunStatus.RUNNING, OrchestrationRunStatus.CANCELLED}
    ),
    OrchestrationRunStatus.BLOCKED: frozenset(
        {
            OrchestrationRunStatus.RUNNING,
            OrchestrationRunStatus.SUSPENDED,
            OrchestrationRunStatus.CANCELLED,
        }
    ),
    OrchestrationRunStatus.UNCERTAIN: frozenset(
        {
            OrchestrationRunStatus.RUNNING,
            OrchestrationRunStatus.FAILED,
            OrchestrationRunStatus.CANCELLED,
        }
    ),
    # terminal states have no outgoing edges
    OrchestrationRunStatus.COMPLETED: frozenset(),
    OrchestrationRunStatus.FAILED: frozenset(),
    OrchestrationRunStatus.CANCELLED: frozenset(),
}


def assert_run_transition(
    current: OrchestrationRunStatus,
    target: OrchestrationRunStatus,
) -> OrchestrationRunStatus:
    """Deterministic run-state guard; illegal jumps raise."""

    if target not in RUN_TRANSITIONS[current]:
        raise ValueError(
            f"illegal orchestration run transition {current.value} -> {target.value}"
        )
    return target


class OrchestrationDependency(BaseModel):
    """One directed edge between node keys (from must settle before to)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_node: str = Field(min_length=1, max_length=128)
    to_node: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.from_node == self.to_node:
            raise ValueError("a node cannot depend on itself")
        return self


class OrchestrationNodeProposal(BaseModel):
    """What the Orchestrator Agent may ask for (plan 6.4) — no execution facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_key: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=MAX_TEXT)
    preferred_agent_role: str = Field(min_length=1, max_length=128)
    required_capabilities: frozenset[Capability]
    resource_refs: tuple[HostResourceRef, ...] = ()
    isolation_mode: Literal["shared_readonly", "worktree", "snapshot", "none"] = (
        "shared_readonly"
    )
    max_model_tokens: int = Field(ge=0)
    max_model_calls: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)
    max_runtime_seconds: int = Field(ge=0)
    failure_policy: Literal["fail_plan", "continue", "retry_once", "require_human"] = (
        "fail_plan"
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        object.__setattr__(
            self,
            "required_capabilities",
            capability_set(sorted(self.required_capabilities)),
        )
        if not self.required_capabilities:
            raise ValueError("node must require at least one capability")
        if (
            self.max_model_tokens == 0
            and self.max_model_calls == 0
            and self.max_tool_calls == 0
        ):
            raise ValueError("node must declare a non-zero budget axis")
        return self


class OrchestrationPlanProposal(BaseModel):
    """The full agent-authored proposal (plan 6.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["zebra.orchestration-plan/1"] = "zebra.orchestration-plan/1"
    objective: str = Field(min_length=1, max_length=MAX_TEXT)
    nodes: tuple[OrchestrationNodeProposal, ...] = Field(min_length=1, max_length=MAX_NODES)
    dependencies: tuple[OrchestrationDependency, ...] = ()
    max_parallelism: int = Field(ge=1, le=MAX_NODES)
    completion_strategy: Literal["all_success", "all_terminal", "any_success"] = (
        "all_success"
    )
    synthesis_instruction: str = Field(min_length=1, max_length=MAX_TEXT)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        keys = [node.node_key for node in self.nodes]
        if len(set(keys)) != len(keys):
            raise ValueError("node keys must be unique")
        known = set(keys)
        for edge in self.dependencies:
            if edge.from_node not in known or edge.to_node not in known:
                raise ValueError("dependencies must reference declared nodes")
        if self.max_parallelism > len(self.nodes):
            raise ValueError("parallelism cannot exceed the node count")
        return self


class BoundOrchestrationNode(BaseModel):
    """A validated node frozen into a snapshot (Control Plane-owned facts)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal: OrchestrationNodeProposal
    child_task_id: TaskId | None = None

    @property
    def node_key(self) -> str:
        return self.proposal.node_key


class OrchestrationPlanSnapshot(BaseModel):
    """The immutable validated plan (plan 6.5) — revision-scoped truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_ref: str = Field(min_length=1, max_length=128)
    plan_revision: int = Field(ge=1)
    parent_task_id: TaskId
    parent_binding_digest: str = Field(min_length=64, max_length=64)
    nodes: tuple[BoundOrchestrationNode, ...] = Field(min_length=1)
    dependencies: tuple[OrchestrationDependency, ...] = ()
    reserved_budget: BudgetReservation
    completion_strategy: Literal["all_success", "all_terminal", "any_success"] = (
        "all_success"
    )
    validated_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.validated_at.tzinfo is None:
            raise ValueError("plan validated_at must be timezone-aware")
        return self

    @property
    def plan_digest(self) -> str:
        canonical = {
            "runRef": self.run_ref,
            "planRevision": self.plan_revision,
            "parentTaskId": str(self.parent_task_id),
            "parentBindingDigest": self.parent_binding_digest,
            "nodes": [
                {
                    "nodeKey": node.node_key,
                    "capabilities": sorted(node.proposal.required_capabilities),
                    "isolation": node.proposal.isolation_mode,
                    "childTaskId": str(node.child_task_id)
                    if node.child_task_id
                    else None,
                }
                for node in self.nodes
            ],
            "dependencies": [
                {"from": edge.from_node, "to": edge.to_node}
                for edge in self.dependencies
            ],
            "reservedBudget": {
                "modelTokens": self.reserved_budget.model_tokens,
                "toolCalls": self.reserved_budget.tool_calls,
                "runtimeSeconds": self.reserved_budget.runtime_seconds,
            },
            "completionStrategy": self.completion_strategy,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def next_revision(
        self,
        *,
        added_nodes: tuple[OrchestrationNodeProposal, ...] = (),
        cancelled_node_keys: tuple[str, ...] = (),
    ) -> OrchestrationPlanSnapshot:
        """Replan rule (plan 6.6): append/cancel only; never rewrite nodes."""

        existing = {node.node_key: node for node in self.nodes}
        for key in cancelled_node_keys:
            if key not in existing:
                raise ValueError(f"cannot cancel unknown node {key}")
        added_keys = {node.node_key for node in added_nodes}
        overlap = added_keys & existing.keys()
        if overlap:
            raise ValueError(f"replan cannot redefine existing nodes: {sorted(overlap)}")
        kept = tuple(
            node for node in self.nodes if node.node_key not in set(cancelled_node_keys)
        )
        bound_added = tuple(BoundOrchestrationNode(proposal=node) for node in added_nodes)
        merged = kept + bound_added
        if not merged:
            raise ValueError("a revision must keep at least one node")
        return OrchestrationPlanSnapshot(
            run_ref=self.run_ref,
            plan_revision=self.plan_revision + 1,
            parent_task_id=self.parent_task_id,
            parent_binding_digest=self.parent_binding_digest,
            nodes=merged,
            dependencies=self.dependencies,
            reserved_budget=self.reserved_budget,
            completion_strategy=self.completion_strategy,
            validated_at=datetime.now(UTC),
        )


def snapshot_from_proposal(
    proposal: OrchestrationPlanProposal,
    *,
    run_ref: str,
    parent_task_id: TaskId,
    parent_binding_digest: str,
    reserved_budget: BudgetReservation,
) -> OrchestrationPlanSnapshot:
    """Freeze one validated proposal into revision 1."""

    return OrchestrationPlanSnapshot(
        run_ref=run_ref,
        plan_revision=FIRST_REVISION,
        parent_task_id=parent_task_id,
        parent_binding_digest=parent_binding_digest,
        nodes=tuple(BoundOrchestrationNode(proposal=node) for node in proposal.nodes),
        dependencies=proposal.dependencies,
        reserved_budget=reserved_budget,
        completion_strategy=proposal.completion_strategy,
        validated_at=datetime.now(UTC),
    )
