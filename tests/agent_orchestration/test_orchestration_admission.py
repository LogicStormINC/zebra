"""03B: one-shot durable admission is optional and outside the outer scope."""

from contextlib import contextmanager

from agent_orchestration.application.orchestration_port import TaskRequestReceipt
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime

from tests.agent_orchestration.test_orchestration_runtime import MemoryStore, _authority, _proposal


def test_dispatch_runs_after_outer_authorization_scope_has_closed() -> None:
    authority = _authority()
    active = False

    @contextmanager
    def authorize(action):
        nonlocal active
        active = True
        try:
            yield authority
        finally:
            active = False

    class Admission:
        def request_task(self, *, run_ref, node_key):
            assert not active
            return TaskRequestReceipt(
                run_ref=run_ref, node_key=node_key, child_task_id="real-child"
            )

    store = MemoryStore()
    runtime = OrchestrationRuntime(store, authorize=authorize, admission=Admission())
    receipt = runtime.propose_plan(_proposal())
    child = runtime.request_task(run_ref=receipt.run_ref, node_key="a")
    assert child.child_task_id == "real-child"
    assert store.node_status == {}


def test_child_resources_are_node_refs_plus_parent_identity_only() -> None:
    from dataclasses import replace
    from uuid import UUID, uuid4

    from agent_core.domain.host_authority import HostResourceRef
    from agent_core.domain.identifiers import TaskId
    from agent_orchestration.application.orchestration_admission import (
        derive_orchestration_child_binding,
    )
    from agent_orchestration.domain.orchestration import OrchestrationNodeProposal

    from tests.agent_storage.test_command_wakeup import _binding
    from tests.agent_storage.test_postgres_orchestration_admission import _build

    parent = _binding(str(uuid4()))
    context = parent.host_capability.host_context
    a, b = HostResourceRef(type="document", id="A"), HostResourceRef(type="document", id="B")
    context = context.model_copy(update={"resource_refs": (*context.resource_refs, a, b)})
    parent = parent.model_copy(
        update={
            "host_capability": parent.host_capability.model_copy(update={"host_context": context})
        }
    )
    authority = replace(
        _authority(),
        parent_task_id=TaskId(UUID(parent.task_id)),
        parent_binding_digest=parent.binding_digest,
    )
    node = OrchestrationNodeProposal(
        node_key="a",
        objective="Collect",
        preferred_agent_role="researcher",
        required_capabilities=frozenset({"agent.execute"}),
        resource_refs=(a,),
        max_model_tokens=50,
        max_model_calls=2,
        max_tool_calls=3,
        max_runtime_seconds=10,
    )
    # The frozen plan is only builder input here; test the actual derived authority.
    from agent_orchestration.domain.orchestration import (
        OrchestrationPlanProposal,
        snapshot_from_proposal,
    )
    from agent_orchestration.domain.orchestration_budget import BudgetReservation

    snapshot = snapshot_from_proposal(
        OrchestrationPlanProposal(
            objective="Read", nodes=(node,), max_parallelism=1, synthesis_instruction="Merge"
        ),
        run_ref="resources",
        parent_task_id=authority.parent_task_id,
        parent_binding_digest=authority.parent_binding_digest,
        reserved_budget=BudgetReservation(model_tokens=50, tool_calls=3, runtime_seconds=10),
    )
    prepared = _build(authority, parent, snapshot, node)
    child = prepared.admission.binding.host_capability.host_context
    assert set(child.resource_refs) == {context.resource_refs[0], a}
    assert b not in child.resource_refs
    assert child.limits.max_model_tokens == 50 and child.limits.max_runtime_seconds == 10
    empty = node.model_copy(update={"resource_refs": ()})
    minimal = derive_orchestration_child_binding(
        parent, prepared.delegation, prepared.admission.session.session_id, empty
    )
    assert minimal.host_capability.host_context.resource_refs == (context.resource_refs[0],)
    import pytest
    from agent_orchestration.application.orchestration_port import OrchestrationToolError

    foreign = HostResourceRef(type="document", id="not-in-parent")
    with pytest.raises(OrchestrationToolError, match="invalid_child"):
        derive_orchestration_child_binding(
            parent,
            prepared.delegation.model_copy(update={"resource_refs": (foreign,)}),
            prepared.admission.session.session_id,
            node.model_copy(update={"resource_refs": (foreign,)}),
            parent_resource_refs=frozenset((*context.resource_refs, foreign)),
        )


def test_current_approved_budget_cannot_be_less_than_claimed_free_balance() -> None:
    from dataclasses import replace

    import pytest
    from agent_orchestration.domain.orchestration_budget import BudgetReservation

    with pytest.raises(ValueError, match="approved budget"):
        replace(
            _authority(),
            approved_budget=BudgetReservation(
                model_tokens=0,
                tool_calls=0,
                runtime_seconds=0,
            ),
        )
