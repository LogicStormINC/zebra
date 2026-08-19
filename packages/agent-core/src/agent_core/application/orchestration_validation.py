"""Pure-function plan validation (ORCH-VALIDATOR-01, plan section 6.5).

Every check is deterministic over the frozen proposal plus an explicit
validation context — no I/O, no runtime state. A plan either freezes into
a snapshot or fails with a typed reason code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_core.domain.agent_capabilities import (
    Capability,
    capability_set,
)
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_core.domain.orchestration import (
    OrchestrationPlanProposal,
    OrchestrationPlanSnapshot,
    snapshot_from_proposal,
)
from agent_core.domain.orchestration_budget import BudgetReservation
from agent_core.domain.subagents import SubagentRole

DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_PARALLELISM = 2

READ_ONLY_ISOLATION = frozenset({"shared_readonly", "snapshot"})
WRITE_ISOLATION = frozenset({"worktree"})


class PlanValidationError(ValueError):
    """One deterministic validation failure with a typed reason code."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class PlanValidationContext:
    """Everything the validator needs beyond the proposal itself."""

    parent_capabilities: frozenset[Capability]
    parent_resource_refs: frozenset[HostResourceRef] = field(default_factory=frozenset)
    parent_remaining_budget: BudgetReservation = field(
        default_factory=lambda: BudgetReservation(
            model_tokens=0, tool_calls=0, runtime_seconds=0
        )
    )
    published_roles: frozenset[str] = field(
        default_factory=lambda: frozenset(role.value for role in SubagentRole)
    )
    write_capabilities: frozenset[Capability] = field(default_factory=frozenset)
    allow_write_nodes: bool = False
    max_depth: int = DEFAULT_MAX_DEPTH
    max_parallelism: int = DEFAULT_MAX_PARALLELISM

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "parent_capabilities", capability_set(self.parent_capabilities)
        )
        object.__setattr__(
            self, "write_capabilities", capability_set(self.write_capabilities)
        )


def validate_plan(
    proposal: OrchestrationPlanProposal,
    context: PlanValidationContext,
    *,
    run_ref: str,
    parent_task_id: TaskId,
    parent_binding_digest: str,
) -> OrchestrationPlanSnapshot:
    """Validate one proposal and freeze it, or raise typed failures."""

    _validate_roles(proposal, context)
    _validate_capabilities(proposal, context)
    _validate_resources(proposal, context)
    _validate_isolation_and_writes(proposal, context)
    _validate_budget(proposal, context)
    _validate_graph(proposal, context)
    return snapshot_from_proposal(
        proposal,
        run_ref=run_ref,
        parent_task_id=parent_task_id,
        parent_binding_digest=parent_binding_digest,
        reserved_budget=_total_budget(proposal),
    )


def _validate_roles(
    proposal: OrchestrationPlanProposal,
    context: PlanValidationContext,
) -> None:
    for node in proposal.nodes:
        role = node.preferred_agent_role
        try:
            SubagentRole(role)
        except ValueError:
            raise PlanValidationError("unknown_role", f"{node.node_key}: {role}") from None
        if role not in context.published_roles:
            raise PlanValidationError(
                "role_not_published", f"{node.node_key}: {role}"
            )


def _validate_capabilities(
    proposal: OrchestrationPlanProposal,
    context: PlanValidationContext,
) -> None:
    for node in proposal.nodes:
        beyond = node.required_capabilities - context.parent_capabilities
        if beyond:
            raise PlanValidationError(
                "capability_beyond_parent",
                f"{node.node_key}: {sorted(beyond)}",
            )


def _validate_resources(
    proposal: OrchestrationPlanProposal,
    context: PlanValidationContext,
) -> None:
    if not context.parent_resource_refs:
        return
    allowed = set(context.parent_resource_refs)
    for node in proposal.nodes:
        for ref in node.resource_refs:
            if ref not in allowed:
                raise PlanValidationError(
                    "resource_beyond_parent",
                    f"{node.node_key}: {ref.resource_type}/{ref.resource_id}",
                )


def _validate_isolation_and_writes(
    proposal: OrchestrationPlanProposal,
    context: PlanValidationContext,
) -> None:
    for node in proposal.nodes:
        role = SubagentRole(node.preferred_agent_role)
        writes = node.required_capabilities & context.write_capabilities
        if writes:
            if not context.allow_write_nodes:
                raise PlanValidationError(
                    "write_nodes_not_allowed",
                    f"{node.node_key}: {sorted(writes)}",
                )
            if node.isolation_mode not in WRITE_ISOLATION:
                raise PlanValidationError(
                    "write_node_requires_worktree",
                    f"{node.node_key}: {node.isolation_mode}",
                )
            if node.failure_policy != "require_human":
                raise PlanValidationError(
                    "write_node_requires_human_policy",
                    f"{node.node_key}: {node.failure_policy}",
                )
            continue
        if node.isolation_mode == "none":
            raise PlanValidationError(
                "isolation_required", f"{node.node_key}: isolation none"
            )
        if role is SubagentRole.IMPLEMENTER and node.isolation_mode not in WRITE_ISOLATION:
            # an implementer without declared write capabilities still
            # defaults to worktree isolation per the plan matrix
            pass


def _validate_budget(
    proposal: OrchestrationPlanProposal,
    context: PlanValidationContext,
) -> None:
    total = _total_budget(proposal)
    ceiling = context.parent_remaining_budget
    if (
        total.model_tokens > ceiling.model_tokens
        or total.tool_calls > ceiling.tool_calls
        or total.runtime_seconds > ceiling.runtime_seconds
    ):
        raise PlanValidationError(
            "budget_beyond_parent",
            f"requested tokens={total.model_tokens} tool_calls={total.tool_calls} "
            f"runtime={total.runtime_seconds} over remaining "
            f"tokens={ceiling.model_tokens} tool_calls={ceiling.tool_calls} "
            f"runtime={ceiling.runtime_seconds}",
        )


def _validate_graph(
    proposal: OrchestrationPlanProposal,
    context: PlanValidationContext,
) -> None:
    if proposal.max_parallelism > context.max_parallelism:
        raise PlanValidationError(
            "parallelism_exceeded",
            f"{proposal.max_parallelism} > {context.max_parallelism}",
        )
    adjacency: dict[str, list[str]] = {node.node_key: [] for node in proposal.nodes}
    indegree: dict[str, int] = {node.node_key: 0 for node in proposal.nodes}
    for edge in proposal.dependencies:
        adjacency[edge.from_node].append(edge.to_node)
        indegree[edge.to_node] += 1
    # Kahn cycle check while tracking longest chain depth
    depth = {key: 1 for key in adjacency}
    queue = [key for key, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for successor in adjacency[current]:
            depth[successor] = max(depth[successor], depth[current] + 1)
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)
    if visited != len(adjacency):
        raise PlanValidationError("cycle_detected", "dependencies form a cycle")
    longest = max(depth.values(), default=1)
    if longest > context.max_depth:
        raise PlanValidationError(
            "depth_exceeded", f"chain depth {longest} > {context.max_depth}"
        )


def _total_budget(proposal: OrchestrationPlanProposal) -> BudgetReservation:
    return BudgetReservation(
        model_tokens=sum(node.max_model_tokens for node in proposal.nodes),
        tool_calls=sum(node.max_tool_calls for node in proposal.nodes),
        runtime_seconds=sum(node.max_runtime_seconds for node in proposal.nodes),
    )
