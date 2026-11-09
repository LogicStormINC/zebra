"""03A: trusted per-call scopes protect both Agent Layer entry points."""

from contextlib import contextmanager, nullcontext
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from agent_core.domain.identifiers import TaskId
from agent_core.domain.tools import ToolCallStatus
from agent_orchestration.application.orchestration_port import OrchestrationToolError
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime
from agent_tools.builtin.orchestration import PlanProposeTool, TaskRequestTool

from tests.agent_orchestration.test_orchestration_runtime import (
    MemoryStore,
    _authority,
    _proposal,
)
from tests.agent_tools.test_orchestration_tools import VALID_PROPOSAL, _call


@pytest.mark.parametrize("action", ["propose", "request"])
def test_no_authorizer_fails_closed_without_store_changes(action: str) -> None:
    store = MemoryStore()
    runtime = OrchestrationRuntime(store)
    with pytest.raises(OrchestrationToolError, match="authority_required"):
        if action == "propose":
            runtime.propose_plan(_proposal())
        else:
            runtime.request_task(run_ref="untrusted-run", node_key="a")
    assert store.runs == store.node_status == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("parent_task_id", UUID(int=0)),
        ("parent_task_id", "not-a-uuid"),
        ("parent_binding_digest", "z" * 64),
        ("parent_binding_digest", "a" * 63),
        ("deployment_namespace", " "),
        ("validation", None),
    ],
)
def test_authority_rejects_malformed_facts(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_authority(), **{field: value})


@pytest.mark.parametrize(
    "changed",
    [
        {"deployment_namespace": "other-product"},
        {"parent_task_id": TaskId(uuid4())},
        {"parent_binding_digest": "b" * 64},
    ],
)
def test_request_checks_namespace_parent_and_binding_before_any_mutation(changed: dict) -> None:
    store = MemoryStore()
    authority = _authority()
    runtime = OrchestrationRuntime(store, authorize=lambda action: nullcontext(authority))
    receipt = runtime.propose_plan(_proposal())
    foreign = OrchestrationRuntime(
        store, authorize=lambda action: nullcontext(replace(authority, **changed))
    )
    before = (dict(store.runs), dict(store.status), dict(store.node_status))
    with pytest.raises(OrchestrationToolError, match="orchestration_forbidden"):
        foreign.request_task(run_ref=receipt.run_ref, node_key="a")
    assert (store.runs, store.status, store.node_status) == before


def test_scope_encloses_store_and_exits_on_success_and_refusal() -> None:
    active = False
    entered = []
    exited = []
    authority = _authority()

    @contextmanager
    def authorize(action):
        nonlocal active
        entered.append(action)
        active = True
        try:
            yield authority
        finally:
            active = False
            exited.append(action)

    class ScopedStore(MemoryStore):
        def create_run(self, snapshot):
            assert active
            super().create_run(snapshot)

        def get_snapshot(self, run_ref, revision=None):
            assert active
            return super().get_snapshot(run_ref, revision)

    store = ScopedStore()
    runtime = OrchestrationRuntime(store, authorize=authorize)
    receipt = runtime.propose_plan(_proposal())
    assert not active
    with pytest.raises(OrchestrationToolError, match="dispatch_unavailable"):
        runtime.request_task(run_ref=receipt.run_ref, node_key="a")
    assert not active
    assert entered == exited == ["propose", "request"]
    assert not store.node_status  # no fabricated child/dispatch state


@pytest.mark.parametrize("tool_action", ["propose", "request"])
def test_each_tool_rechecks_current_authority_after_revocation(tool_action: str) -> None:
    authority = _authority()
    revoked = False
    calls = []

    @contextmanager
    def authorize(action):
        calls.append(action)
        if revoked:
            raise OrchestrationToolError("orchestration_forbidden", "current authority revoked")
        yield authority

    store = MemoryStore()
    runtime = OrchestrationRuntime(store, authorize=authorize)
    receipt = runtime.propose_plan(_proposal())
    revoked = True
    if tool_action == "propose":
        result = PlanProposeTool(runtime).handle(
            _call("orchestration.plan.propose", VALID_PROPOSAL)
        )
    else:
        result = TaskRequestTool(runtime).handle(
            _call(
                "orchestration.task.request",
                {
                    "run_ref": receipt.run_ref,
                    "node_key": "a",
                    "_parent_task_id": str(authority.parent_task_id),
                    "_budget_tokens": 10**12,
                },
            )
        )
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "orchestration_forbidden"
    assert calls == ["propose", tool_action]
    assert len(store.runs) == 1 and not store.node_status


def test_forged_model_budget_capabilities_and_identity_do_not_expand_trusted_context() -> None:
    authority = _authority()
    store = MemoryStore()
    runtime = OrchestrationRuntime(store, authorize=lambda action: nullcontext(authority))
    forged = {
        **VALID_PROPOSAL,
        "_parent_task_id": str(uuid4()),
        "_budget_tokens": 10**12,
        "_parent_capabilities": ["anything"],
        "_parent_binding_digest": "b" * 64,
    }
    result = PlanProposeTool(runtime).handle(_call("orchestration.plan.propose", forged))
    assert result.status is ToolCallStatus.EXECUTED
    snapshot = next(iter(store.runs.values()))
    assert snapshot.parent_task_id == authority.parent_task_id
    assert snapshot.parent_binding_digest == authority.parent_binding_digest

    reduced = replace(
        authority, validation=replace(authority.validation, parent_capabilities=frozenset())
    )
    refusing = OrchestrationRuntime(store, authorize=lambda action: nullcontext(reduced))
    denied = PlanProposeTool(refusing).handle(_call("orchestration.plan.propose", forged))
    assert denied.status is ToolCallStatus.FAILED
    assert len(store.runs) == 1

    no_budget = replace(
        authority,
        validation=replace(
            authority.validation,
            parent_remaining_budget=authority.validation.parent_remaining_budget.model_copy(
                update={"model_tokens": 0}
            ),
        ),
    )
    refusing = OrchestrationRuntime(store, authorize=lambda action: nullcontext(no_budget))
    denied = PlanProposeTool(refusing).handle(_call("orchestration.plan.propose", forged))
    assert denied.status is ToolCallStatus.FAILED
    assert denied.metadata["reason"] == "budget_beyond_parent"
    assert len(store.runs) == 1


def test_failed_write_exits_authorization_scope_without_receipt() -> None:
    authority = _authority()
    events = []

    @contextmanager
    def authorize(action):
        events.append("entered")
        try:
            yield authority
        except RuntimeError:
            events.append("rollback")
            raise
        finally:
            events.append("exited")

    class FailingStore(MemoryStore):
        def create_run(self, snapshot):
            raise RuntimeError("write failed")

    store = FailingStore()
    runtime = OrchestrationRuntime(store, authorize=authorize)
    with pytest.raises(RuntimeError, match="write failed"):
        runtime.propose_plan(_proposal())
    assert events == ["entered", "rollback", "exited"]
    assert not store.runs


@pytest.mark.parametrize("action", ["propose", "request"])
def test_missing_authority_maps_to_typed_failure_at_both_tools(action: str) -> None:
    store = MemoryStore()
    runtime = OrchestrationRuntime(store)
    if action == "propose":
        result = PlanProposeTool(runtime).handle(
            _call("orchestration.plan.propose", VALID_PROPOSAL)
        )
    else:
        result = TaskRequestTool(runtime).handle(
            _call("orchestration.task.request", {"run_ref": "foreign", "node_key": "a"})
        )
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "orchestration_authority_required"
    assert store.runs == store.node_status == {}


@pytest.mark.parametrize("action", ["propose", "request"])
def test_provider_without_authority_returns_typed_tool_failure(action: str) -> None:
    store = MemoryStore()
    runtime = OrchestrationRuntime(store, authorize=lambda action: nullcontext(None))
    if action == "propose":
        result = PlanProposeTool(runtime).handle(
            _call("orchestration.plan.propose", VALID_PROPOSAL)
        )
    else:
        result = TaskRequestTool(runtime).handle(
            _call("orchestration.task.request", {"run_ref": "foreign", "node_key": "a"})
        )
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "invalid_authority"
    assert store.runs == store.node_status == {}
