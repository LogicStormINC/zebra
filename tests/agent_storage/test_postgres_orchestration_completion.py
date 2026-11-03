"""03C durable terminal decisions, exact revisions and fail-closed synthesis."""

from uuid import uuid4

import pytest
from agent_orchestration.application.orchestration_port import OrchestrationToolError
from agent_orchestration.application.orchestration_runtime import OrchestrationRuntime
from agent_orchestration.application.orchestration_scheduling import NodeOutcome
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.orchestration import (
    OrchestrationStorageError,
    PostgresOrchestrationStore,
)

from tests.agent_storage.test_postgres_orchestration import _snapshot


@pytest.fixture
def namespace(postgres_dsn):
    ns = "completion-" + str(uuid4())
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=ns)
    return ns


@pytest.fixture
def running(namespace, postgres_dsn):
    store = PostgresOrchestrationStore(postgres_dsn, deployment_namespace=namespace)
    snapshot = _snapshot("completion-" + str(uuid4()))
    store.create_run(snapshot)
    runtime = OrchestrationRuntime(store)
    runtime.materialize(snapshot.run_ref)
    store.transition_node(snapshot.run_ref, "a", "running")
    return store, runtime, snapshot


def test_completion_is_idempotent_and_different_terminal_conflicts(running):
    store, runtime, snap = running
    runtime.complete_node(snap.run_ref, "a", NodeOutcome.COMPLETED, revision=1)
    runtime.complete_node(snap.run_ref, "a", NodeOutcome.COMPLETED, revision=1)
    with pytest.raises(OrchestrationStorageError, match="terminal"):
        runtime.complete_node(snap.run_ref, "a", NodeOutcome.FAILED, revision=1)
    assert store.read_node_statuses(snap.run_ref)["a"] == "completed"


def test_failure_policy_is_persistent(running):
    store, runtime, snap = running
    runtime.complete_node(snap.run_ref, "a", NodeOutcome.FAILED, revision=1)
    assert store.read_node_statuses(snap.run_ref) == {"a": "failed", "b": "cancelled"}
    assert store.read_run_status(snap.run_ref) == "failed"


def test_old_revision_cannot_advance_current_node(running):
    store, runtime, snap = running
    store.append_plan_revision(snap.next_revision())
    with pytest.raises(OrchestrationStorageError, match="revision"):
        runtime.complete_node(snap.run_ref, "a", NodeOutcome.COMPLETED, revision=1)
    assert store.read_node_statuses(snap.run_ref)["a"] == "blocked"


def test_unexpected_source_status_cannot_complete(running):
    store, runtime, snap = running
    with pytest.raises(OrchestrationStorageError, match="source"):
        runtime.complete_node(snap.run_ref, "b", NodeOutcome.COMPLETED, revision=1)
    assert store.read_node_statuses(snap.run_ref)["b"] == "blocked"


def test_production_synthesis_requires_persisted_gate(running):
    store, _, snap = running
    runtime = OrchestrationRuntime(store, require_persisted_gate=True)
    with pytest.raises(OrchestrationToolError, match="gate_authority_unavailable"):
        runtime.synthesize(snap.run_ref)


@pytest.mark.parametrize(
    "policy,run_status,sibling",
    [
        ("retry_once", "blocked", "blocked"),
        ("require_human", "blocked", "blocked"),
        ("continue", "running", "skipped"),
    ],
)
def test_persisted_failure_policy_does_not_create_a_replacement_child(
    namespace,
    postgres_dsn,
    policy,
    run_status,
    sibling,
):
    store = PostgresOrchestrationStore(postgres_dsn, deployment_namespace=namespace)
    snap = _snapshot("policy-" + str(uuid4()))
    first = snap.nodes[0]
    changed = first.model_copy(
        update={"proposal": first.proposal.model_copy(update={"failure_policy": policy})}
    )
    snap = snap.model_copy(update={"nodes": (changed, snap.nodes[1])})
    store.create_run(snap)
    runtime = OrchestrationRuntime(store)
    runtime.materialize(snap.run_ref)
    store.transition_node(snap.run_ref, "a", "running")
    runtime.complete_node(snap.run_ref, "a", NodeOutcome.TIMED_OUT, revision=1)
    assert store.read_run_status(snap.run_ref) == run_status
    assert store.read_node_statuses(snap.run_ref) == {"a": "failed", "b": sibling}
    assert not runtime.evaluate(snap.run_ref).ready_nodes


def test_wrong_child_cannot_notify_node(running):
    store, runtime, snap = running
    with pytest.raises(OrchestrationStorageError, match="child"):
        runtime.complete_node(
            snap.run_ref, "a", NodeOutcome.COMPLETED, revision=1, child_task_id=str(uuid4())
        )
    assert store.read_node_statuses(snap.run_ref)["a"] == "running"


def test_concurrent_duplicate_terminal_is_idempotent(running):
    from concurrent.futures import ThreadPoolExecutor

    store, runtime, snap = running
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(runtime.complete_node, snap.run_ref, "a", NodeOutcome.COMPLETED, revision=1)
            for _ in range(2)
        ]
        for future in futures:
            future.result()
    assert store.read_node_statuses(snap.run_ref)["a"] == "completed"


def test_recorder_budget_callback_inside_actual_locked_work_unit(postgres_dsn):
    from agent_storage.postgres.coverage_authority import lock_coverage_lease
    from agent_storage.postgres.leases import lock_session_lease_boundary
    from agent_storage.postgres.work_unit import postgres_work_unit
    from zebra_agent_worker.worker_budget import BudgetExecutionCheck, TaskBudgetGate

    from tests.agent_storage.test_postgres_orchestration_admission import setup
    from tests.agent_storage.test_postgres_worker_budget import started

    store, binding, database = started(setup.__wrapped__(postgres_dsn))
    callback = BudgetExecutionCheck(lambda: None)
    callback.gate = TaskBudgetGate(store, binding)
    with postgres_work_unit(database), database.connect() as connection:
        lock_session_lease_boundary(connection, store.namespace, binding.session_id)
        lock_coverage_lease(connection, store.namespace, binding.session_id)
        connection.execute("SET LOCAL statement_timeout='1000ms'")
        callback()
