"""Optional real PostgreSQL checks, exclusively in the existing disposable schema."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import psycopg
import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_execution import CoverageExecutionBudget
from agent_core.domain.coverage_persistence import CoverageRunBinding, coverage_manifest_bytes
from agent_core.domain.coverage_validation import expected_units, manifest_digest
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres.coverage import PostgresCoverageStore

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import (  # noqa: F401
    batch,
    bind,
    dsn,
    env,
    source_counts,
)


@pytest.mark.parametrize(
    "budget",
    [
        CoverageExecutionBudget(max_attempts=1, max_input_bytes=100),
        CoverageExecutionBudget(max_attempts=100, max_input_bytes=3),
    ],
)
def test_attempt_budget_is_durable_across_store_restart(env, budget):  # noqa: F811
    bind(env)
    key = expected_units(env.binding.contract, env.items)[0]
    before = source_counts(env)
    sequence = env.store.reserve_attempt(
        env.binding, key, input_bytes=3, budget=budget, fence=env.fence
    )
    assert sequence > 0 and source_counts(env) == before + 1
    fresh = PostgresCoverageStore(env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts)
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        fresh.reserve_attempt(env.binding, key, input_bytes=3, budget=budget, fence=env.fence)
    assert source_counts(env) == before + 1
    assert fresh.counts(env.binding.namespace, env.binding.run_id) == (4, 0)


def test_attempt_budget_policy_cannot_be_increased_on_restart(env):  # noqa: F811
    bind(env)
    key = expected_units(env.binding.contract, env.items)[0]
    budget = CoverageExecutionBudget(max_attempts=2, max_input_bytes=6)
    env.store.reserve_attempt(env.binding, key, input_bytes=3, budget=budget, fence=env.fence)
    before = source_counts(env)
    fresh = PostgresCoverageStore(env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts)
    with pytest.raises(ValueError, match="budget cannot change"):
        fresh.reserve_attempt(
            env.binding,
            key,
            input_bytes=3,
            budget=budget.model_copy(update={"max_attempts": 100}),
            fence=env.fence,
        )
    assert source_counts(env) == before
    assert fresh.counts(env.binding.namespace, env.binding.run_id) == (4, 0)


def test_rebuild_preserves_frozen_budget_and_consumed_attempt_counts(env):  # noqa: F811
    bind(env)
    key = expected_units(env.binding.contract, env.items)[0]
    budget = CoverageExecutionBudget(max_attempts=1, max_input_bytes=3)
    env.store.reserve_attempt(env.binding, key, input_bytes=3, budget=budget, fence=env.fence)
    before = source_counts(env)
    env.store.rebuild(env.binding.namespace, env.binding.run_id)
    fresh = PostgresCoverageStore(env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts)
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        fresh.reserve_attempt(env.binding, key, input_bytes=3, budget=budget, fence=env.fence)
    for changed in (
        budget.model_copy(update={"max_attempts": 2}),
        budget.model_copy(update={"max_input_bytes": 6}),
    ):
        with pytest.raises(ValueError, match="budget cannot change"):
            fresh.reserve_attempt(env.binding, key, input_bytes=3, budget=changed, fence=env.fence)
    with psycopg.connect(env.dsn) as connection:
        counters = connection.execute(
            """SELECT attempt_budget,attempt_count,input_bytes_count FROM coverage_runs
               WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
            (NAMESPACE, env.binding.namespace, env.binding.run_id),
        ).fetchone()
    assert counters == (budget.model_dump(mode="json"), 1, 3)
    assert source_counts(env) == before
    assert fresh.counts(env.binding.namespace, env.binding.run_id) == (4, 0)


def test_stale_fence_cannot_reserve_attempt(env):  # noqa: F811
    bind(env)
    key = expected_units(env.binding.contract, env.items)[0]
    before = source_counts(env)
    env.leases.release(env.session.session_id, fence=env.fence)
    env.leases.acquire(
        env.session.session_id, owner_instance_id="replacement", ttl=timedelta(minutes=5)
    )
    with pytest.raises(LeaseLostError):
        env.store.reserve_attempt(
            env.binding,
            key,
            input_bytes=3,
            budget=CoverageExecutionBudget(max_attempts=10, max_input_bytes=100),
            fence=env.fence,
        )
    assert source_counts(env) == before
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (4, 0)


def test_accepted_record_read_is_exact_and_accepted_unit_cannot_be_attempted(env):  # noqa: F811
    bind(env)
    keys = expected_units(env.binding.contract, env.items)
    request = batch(env, keys=(keys[0], keys[2]))
    env.store.commit(request, fence=env.fence)
    fresh = PostgresCoverageStore(env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts)
    assert fresh.accepted_for_record("tenant-a", "run-1", env.items[0].record_id) == (
        request.results[0],
    )
    assert fresh.accepted_for_record("tenant-a", "run-1", env.items[1].record_id) == (
        request.results[1],
    )
    assert fresh.accepted_for_record("tenant-a", "run-1", "invented") == ()
    assert fresh.accepted_for_record("another-tenant", "run-1", env.items[0].record_id) == ()
    before = source_counts(env)
    with pytest.raises(ValueError, match="missing exact coverage unit"):
        fresh.reserve_attempt(
            env.binding,
            keys[0],
            input_bytes=3,
            budget=CoverageExecutionBudget(max_attempts=10, max_input_bytes=100),
            fence=env.fence,
        )
    assert source_counts(env) == before
    assert fresh.counts("tenant-a", "run-1") == (4, 2)


def test_accepted_record_read_pages_1001_parts_and_filters_check_id(env):  # noqa: F811
    record = env.items[0]
    env.items = (record.model_copy(update={"parts": tuple(
        record.parts[0].model_copy(update={"id": f"body-{index}"}) for index in range(1001)
    )}),)
    contract = env.binding.contract.model_copy(update={"checks": (
        *env.binding.contract.checks,
        env.binding.contract.checks[0].model_copy(update={"id": "other-check"}),
    )})
    body = coverage_manifest_bytes(env.items)
    artifact = env.artifacts.store_payload(ArtifactPayloadWrite(
        session_id=env.session.session_id, kind="coverage-manifest", mime_type="application/json",
        payload=body, created_at=datetime.now(UTC),
    ))
    snapshot = env.binding.snapshot.model_copy(update={
        "contract_digest": contract.digest,
        "manifest_digest": manifest_digest(contract, env.items), "record_count": 1,
        "manifest_artifact_ref": artifact.uri,
    })
    env.binding = CoverageRunBinding(
        namespace=env.binding.namespace, session_id=env.binding.session_id,
        task_id=env.binding.task_id, run_id="large-record", contract=contract, snapshot=snapshot,
        manifest_artifact_digest=sha256(body).hexdigest(),
    )
    bind(env)
    keys = expected_units(contract, env.items)
    accepted = ()
    for offset in range(0, len(keys), 1000):
        request = batch(env, keys=keys[offset:offset + 1000], key=f"page-{offset}")
        env.store.commit(request, fence=env.fence)
        accepted += request.results
    before = source_counts(env)
    fresh = PostgresCoverageStore(env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts)
    assert fresh.accepted_for_record("tenant-a", "large-record", record.record_id) == accepted
    for check in contract.checks:
        filtered = fresh.accepted_for_record(
            "tenant-a", "large-record", record.record_id, check_id=check.id,
        )
        assert filtered == tuple(item for item in accepted if item.key.check_id == check.id)
        assert sum(item.key.kind == "part" for item in filtered) == 1001
        assert sum(item.key.kind == "record_merge" for item in filtered) == 1
    assert fresh.accepted_for_record(
        "tenant-a", "large-record", record.record_id, check_id="missing-check",
    ) == ()
    assert fresh.accepted_for_record("another-tenant", "large-record", record.record_id) == ()
    assert fresh.counts("tenant-a", "large-record") == (2004, 2004)
    assert source_counts(env) == before
