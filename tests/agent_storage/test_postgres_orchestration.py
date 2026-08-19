"""Real-PostgreSQL orchestration projection tests (v27, ORCH-PG-01)."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from agent_core.domain.agent_capabilities import capability_set
from agent_core.domain.identifiers import TaskId
from agent_core.domain.orchestration import (
    OrchestrationDependency,
    OrchestrationNodeProposal,
    OrchestrationPlanProposal,
    OrchestrationRunStatus,
    snapshot_from_proposal,
)
from agent_core.domain.orchestration_budget import BudgetReservation
from agent_storage import (
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.orchestration import (
    OrchestrationStorageError,
    PostgresOrchestrationStore,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> str:
    deployment_namespace = f"orch-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=deployment_namespace)
    return deployment_namespace


def _node(key: str) -> OrchestrationNodeProposal:
    return OrchestrationNodeProposal(
        node_key=key,
        objective=f"Objective {key}",
        preferred_agent_role="researcher",
        required_capabilities=frozenset(capability_set(["evidence.read"])),
        max_model_tokens=100,
        max_model_calls=2,
        max_tool_calls=3,
        max_runtime_seconds=60,
    )


def _proposal() -> OrchestrationPlanProposal:
    return OrchestrationPlanProposal(
        objective="Analyze",
        nodes=(_node("a"), _node("b")),
        dependencies=(OrchestrationDependency(from_node="a", to_node="b"),),
        max_parallelism=1,
        synthesis_instruction="Merge",
    )


def _snapshot(run_ref: str, revision: int = 1) -> object:
    proposal = _proposal()
    snapshot = snapshot_from_proposal(
        proposal,
        run_ref=run_ref,
        parent_task_id=TaskId(uuid4()),
        parent_binding_digest="a" * 64,
        reserved_budget=BudgetReservation(
            model_tokens=10_000, tool_calls=50, runtime_seconds=600
        ),
    )
    return snapshot if revision == 1 else snapshot.next_revision()


def test_create_run_and_read_snapshot_roundtrip(
    namespace: str, postgres_dsn: str
) -> None:
    store = PostgresOrchestrationStore(postgres_dsn, deployment_namespace=namespace)
    snapshot = _snapshot("run-1")
    store.create_run(snapshot)
    loaded = store.get_snapshot("run-1")
    assert loaded is not None
    assert loaded.plan_digest == snapshot.plan_digest
    assert store.get_latest_revision("run-1") == 1


def test_revision_append_is_monotonic_and_digest_changes(
    namespace: str, postgres_dsn: str
) -> None:
    store = PostgresOrchestrationStore(postgres_dsn, deployment_namespace=namespace)
    first = _snapshot("run-2")
    store.create_run(first)
    second = first.next_revision(added_nodes=(_node("c"),))
    store.append_plan_revision(second)
    assert store.get_latest_revision("run-2") == 2
    loaded = store.get_snapshot("run-2")
    assert loaded is not None
    assert loaded.plan_digest == second.plan_digest
    assert first.plan_digest != second.plan_digest
    with pytest.raises(OrchestrationStorageError):
        store.append_plan_revision(second)  # same revision again


def test_run_transitions_are_cas_guarded(namespace: str, postgres_dsn: str) -> None:
    store = PostgresOrchestrationStore(postgres_dsn, deployment_namespace=namespace)
    store.create_run(_snapshot("run-3"))
    store.transition_run(
        "run-3", OrchestrationRunStatus.VALIDATED, OrchestrationRunStatus.MATERIALIZING
    )
    store.transition_run(
        "run-3", OrchestrationRunStatus.MATERIALIZING, OrchestrationRunStatus.RUNNING
    )
    # stale CAS fails closed
    with pytest.raises(OrchestrationStorageError):
        store.transition_run(
            "run-3",
            OrchestrationRunStatus.VALIDATED,
            OrchestrationRunStatus.MATERIALIZING,
        )
    # illegal domain jump fails before SQL
    with pytest.raises(ValueError, match="illegal"):
        store.transition_run(
            "run-3", OrchestrationRunStatus.RUNNING, OrchestrationRunStatus.COMPLETED
        )


def test_result_bundle_and_gate_receipt_roundtrip(
    namespace: str, postgres_dsn: str
) -> None:
    store = PostgresOrchestrationStore(postgres_dsn, deployment_namespace=namespace)
    child = TaskId(uuid4())
    receipt_id = store.record_gate_receipt(
        child_task_id=child,
        gate_name="research.evidence",
        passed=True,
        reason_code="evidence_satisfied",
    )
    store.record_result_bundle(
        child_task_id=child,
        result_digest="b" * 64,
        summary="found the proof",
        artifact_refs=("artifact://1",),
        evidence_digests=("c" * 64,),
        gate_receipt_id=receipt_id,
    )
    bundle = store.get_result_bundle(child)
    assert bundle is not None
    assert bundle["result_digest"] == "b" * 64
    assert bundle["gate_receipt_id"] == receipt_id
    assert bundle["artifact_refs"] == ("artifact://1",)
