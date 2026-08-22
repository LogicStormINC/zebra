"""Plan validator tests: every rejection branch plus the happy freeze."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_orchestration.application.orchestration_validation import (
    PlanValidationContext,
    PlanValidationError,
    validate_plan,
)
from agent_orchestration.domain.orchestration import (
    OrchestrationDependency,
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
)
from agent_orchestration.domain.orchestration_budget import BudgetReservation

PARENT_CAPS = capability_set(["agent.execute", "evidence.read", "timeline.read"])
WRITE_CAPS = capability_set(["note.write"])


def _node(
    key: str,
    *,
    caps: frozenset | None = None,
    isolation: str = "shared_readonly",
    policy: str = "fail_plan",
    resources: tuple[HostResourceRef, ...] = (),
    role: str = "researcher",
) -> OrchestrationNodeProposal:
    return OrchestrationNodeProposal(
        node_key=key,
        objective=f"Objective {key}",
        preferred_agent_role=role,
        required_capabilities=(
            caps if caps is not None else frozenset(capability_set(["evidence.read"]))
        ),
        resource_refs=resources,
        isolation_mode=isolation,  # type: ignore[arg-type]
        max_model_tokens=100,
        max_model_calls=2,
        max_tool_calls=3,
        max_runtime_seconds=60,
        failure_policy=policy,  # type: ignore[arg-type]
    )


def _context(**overrides: object) -> PlanValidationContext:
    payload: dict[str, object] = {
        "parent_capabilities": PARENT_CAPS,
        "parent_remaining_budget": BudgetReservation(
            model_tokens=1000, tool_calls=20, runtime_seconds=600
        ),
        "write_capabilities": WRITE_CAPS,
    }
    payload.update(overrides)
    return PlanValidationContext(**payload)  # type: ignore[arg-type]


def _validate(
    proposal: OrchestrationPlanProposal,
    context: PlanValidationContext,
) -> object:
    return validate_plan(
        proposal,
        context,
        run_ref="run-test",
        parent_task_id=TaskId(uuid4()),
        parent_binding_digest="a" * 64,
    )


class TestHappyPath:
    def test_valid_plan_freezes_into_a_snapshot(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Analyze",
            nodes=(_node("a"), _node("b")),
            dependencies=(OrchestrationDependency(from_node="a", to_node="b"),),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        snapshot = _validate(proposal, _context())
        assert snapshot.plan_revision == 1
        assert len(snapshot.nodes) == 2


class TestRejections:
    def test_cycle_detected(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Cycle",
            nodes=(_node("a"), _node("b")),
            dependencies=(
                OrchestrationDependency(from_node="a", to_node="b"),
                OrchestrationDependency(from_node="b", to_node="a"),
            ),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(proposal, _context())
        assert exc.value.reason_code == "cycle_detected"

    def test_unknown_role(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Role",
            nodes=(_node("a", role="wizard"),),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(proposal, _context())
        assert exc.value.reason_code == "unknown_role"

    def test_role_not_published(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Role",
            nodes=(_node("a"),),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(proposal, _context(published_roles=frozenset({"tester"})))
        assert exc.value.reason_code == "role_not_published"

    def test_capability_beyond_parent(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Caps",
            nodes=(
                _node("a", caps=frozenset(capability_set(["host.business.write"]))),
            ),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(proposal, _context())
        assert exc.value.reason_code == "capability_beyond_parent"

    def test_resource_beyond_parent(self) -> None:
        granted = frozenset({HostResourceRef(type="host-a.event", id="evt-1")})
        proposal = OrchestrationPlanProposal(
            objective="Resources",
            nodes=(
                _node(
                    "a",
                    resources=(HostResourceRef(type="host-a.event", id="evt-9"),),
                ),
            ),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(proposal, _context(parent_resource_refs=granted))
        assert exc.value.reason_code == "resource_beyond_parent"

    def test_budget_beyond_parent(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Budget",
            nodes=(_node("a"), _node("b"), _node("c")),
            max_parallelism=2,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(
                proposal,
                _context(
                    parent_remaining_budget=BudgetReservation(
                        model_tokens=150, tool_calls=20, runtime_seconds=600
                    ),
                ),
            )
        assert exc.value.reason_code == "budget_beyond_parent"

    def test_write_nodes_rejected_in_first_version(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Write",
            nodes=(
                _node(
                    "w",
                    caps=frozenset(capability_set(["note.write"])),
                    isolation="worktree",
                    policy="require_human",
                ),
            ),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(proposal, _context(parent_capabilities=PARENT_CAPS | WRITE_CAPS))
        assert exc.value.reason_code == "write_nodes_not_allowed"

    def test_write_node_requires_worktree_and_human_policy(self) -> None:
        proposal_factory = lambda isolation, policy: OrchestrationPlanProposal(  # noqa: E731
            objective="Write",
            nodes=(
                _node(
                    "w",
                    caps=frozenset(capability_set(["note.write"])),
                    isolation=isolation,
                    policy=policy,
                ),
            ),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(
                proposal_factory("shared_readonly", "require_human"),
                _context(parent_capabilities=PARENT_CAPS | WRITE_CAPS, allow_write_nodes=True),
            )
        assert exc.value.reason_code == "write_node_requires_worktree"
        with pytest.raises(PlanValidationError) as exc:
            _validate(
                proposal_factory("worktree", "continue"),
                _context(parent_capabilities=PARENT_CAPS | WRITE_CAPS, allow_write_nodes=True),
            )
        assert exc.value.reason_code == "write_node_requires_human_policy"

    def test_parallelism_exceeded(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Parallel",
            nodes=(_node("a"), _node("b")),
            max_parallelism=2,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(proposal, _context(max_parallelism=1))
        assert exc.value.reason_code == "parallelism_exceeded"

    def test_depth_exceeded(self) -> None:
        proposal = OrchestrationPlanProposal(
            objective="Deep",
            nodes=(_node("a"), _node("b"), _node("c")),
            dependencies=(
                OrchestrationDependency(from_node="a", to_node="b"),
                OrchestrationDependency(from_node="b", to_node="c"),
            ),
            max_parallelism=1,
            synthesis_instruction="Merge",
        )
        with pytest.raises(PlanValidationError) as exc:
            _validate(proposal, _context(max_depth=2))
        assert exc.value.reason_code == "depth_exceeded"
