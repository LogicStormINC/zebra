"""Real Worker/PG progress; provider, signed Host and S3 remain explicit fixtures."""
# ruff: noqa: F811

import json
from datetime import UTC, datetime

import pytest
from agent_core.domain.coverage_validation import expected_units, manifest_digest
from agent_core.domain.events import EventType
from agent_core.domain.host_authority import MAX_MODEL_TOKENS
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
from agent_storage.postgres.command_wakeup_recovery import (
    RecoveryStatus,
    continue_coverage_command,
    recover_command_batch,
)

from tests.agent_integrations.test_coverage_snapshot_preparation import setup_source
from tests.agent_storage.test_coverage_command_recovery import native_snapshot
from tests.worker.coverage_model_cloud_fixtures import (
    CAPACITY,
    METADATA,
    NAMESPACE,
    dsn,  # noqa: F401
    postgres_dsn,  # noqa: F401
)
from tests.worker.coverage_model_cloud_fixtures import (
    model_cloud as base_model_cloud,
)
from tests.worker.test_coverage_dispatch import native_handoff, native_worker  # noqa: F401


@pytest.fixture
def part_count():
    return 6


@pytest.fixture
def model_cloud(dsn, request, part_count):
    original = base_model_cloud.__wrapped__(dsn, request)
    env = next(original)
    try:
        total_tokens = min(CAPACITY * part_count, MAX_MODEL_TOKENS)
        env.host = env.host.model_copy(
            update={
                "limits": env.host.limits.model_copy(
                    update={"max_model_tokens": total_tokens}
                )
            }
        )
        env.admission = env.admission.model_copy(
            update={
                "max_model_calls": part_count,
                "max_model_tokens": total_tokens,
            }
        )
        source, wire, _ = setup_source(
            tuple(f"native part {i}".encode() for i in range(part_count)),
            session_id=env.session,
            authority=env.host,
            now=lambda: datetime.now(UTC),
        )

        def mutate(name, value):
            if name in {"create", "get"}:
                value["snapshot"].update(
                    contract_digest=env.admission.contract.digest,
                    manifest_digest=manifest_digest(env.admission.contract, wire.records),
                    as_of=env.now.isoformat(),
                    expires_at=env.host.expires_at.isoformat(),
                )
                value["sealed_at"] = env.now.isoformat()
            return value

        wire.mutate = mutate
        data = env.task_binding.model_dump()
        data["host_capability"].update(
            host_context=env.host, grant_digest=host_context_digest(env.host)
        )
        env.task_binding = TaskBindingSnapshot.model_validate(data)
        env.host_source, env.wire = source, wire
        yield env
    finally:
        original.close()


def semantic_calls(env):
    return sum(r.url.path == "/chat/completions" for r in env.native_requests)


def check(env):
    return lambda conn, ns, pending, receipt: env.service._coverage_runtime.recovery_check(
        env.service, conn, ns, pending, receipt
    )


def reply_for(env, key):
    env.reply["choices"][0]["message"]["content"] = json.dumps(
        {
            "key": key.model_dump(mode="json"),
            "outcome": "clear",
            "categories": [],
            "quotes": [],
        }
    )


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
def test_native_multipart_progress_exceeds_five_generations_and_certifies(native_worker):
    env = native_worker
    keys = expected_units(env.admission.contract, env.wire.records)
    assert len(keys) == 12
    with env.database.connect() as conn:
        created = conn.execute("SELECT created_at FROM session_command_pending").fetchone()
    deadlines = []
    for index, key in enumerate(keys):
        reply_for(env, key)
        handoff = native_handoff(env)
        assert handoff.status is HandoffStatus.ACCEPTED
        result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
        assert result.session.status is (
            SessionStatus.COMPLETED if index == len(keys) - 1 else SessionStatus.RUNNING
        )
        with env.database.connect() as conn:
            assert (
                conn.execute("SELECT created_at FROM session_command_pending").fetchone() == created
            )
            row = conn.execute(
                "SELECT policy FROM coverage_model_ledger WHERE run_id=%s",
                (f"coverage-{env.session}",),
            ).fetchone()
            deadlines.append(row["policy"]["deadline"])
    assert len(set(deadlines)) == 1 and semantic_calls(env) == 6
    with env.database.connect() as conn:
        rows = conn.execute(
            "SELECT reason,coverage_proof FROM command_recovery_attempts ORDER BY wake_generation"
        ).fetchall()
        assert len(rows) == 11
        assert all(r["reason"] == "coverage_continuation" for r in rows)
        assert [r["coverage_proof"]["accepted_count"] for r in rows] == list(range(1, 12))
        assert len({r["coverage_proof"]["expected_digest"] for r in rows}) == 1
    assert (
        sum(
            e.event_type is EventType.COVERAGE_REPORT_CERTIFIED
            for e in env.events.list_for_session(env.session)
        )
        == 1
    )


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("part_count", [1])
def test_prebudget_process_crash_recovers_original_run_without_extra_http(
    native_worker, monkeypatch
):
    from agent_storage.postgres.coverage import PostgresCoverageStore

    class ProcessCrash(BaseException):
        pass

    env = native_worker
    first = native_handoff(env)
    reached = []

    def crash(self, binding, *, fence):
        reached.append(binding.run_id)
        raise ProcessCrash()

    with monkeypatch.context() as patch:
        patch.setattr(PostgresCoverageStore, "initialize_model_budget", crash)
        with pytest.raises(ProcessCrash):
            env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    assert reached == [f"coverage-{env.session}"] and semantic_calls(env) == 0
    with env.database.connect() as conn:
        assert not conn.execute(
            "SELECT 1 FROM coverage_model_ledger WHERE run_id=%s", (reached[0],)
        ).fetchall()
        conn.execute("UPDATE session_command_pending SET recovery_due_at=clock_timestamp()")
        conn.execute("UPDATE broker_outbox SET status='published',published_at=clock_timestamp()")
    recovered = recover_command_batch(
        env.dsn, deployment_namespace=NAMESPACE, scope=env.scope, coverage_check=check(env)
    )
    assert len(recovered) == 1 and recovered[0].status is RecoveryStatus.APPROVED
    keys = expected_units(env.admission.contract, env.wire.records)
    for key in keys:
        reply_for(env, key)
        handoff = native_handoff(env)
        assert handoff.status is HandoffStatus.ACCEPTED
        result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.COMPLETED and semantic_calls(env) == 1
    assert (
        sum(
            e.event_type is EventType.COVERAGE_MANIFEST_COMMITTED
            for e in env.events.list_for_session(env.session)
        )
        == 1
    )


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("part_count", [1])
def test_no_progress_continuation_cannot_create_another_wake(native_worker):
    env = native_worker
    key = expected_units(env.admission.contract, env.wire.records)[0]
    reply_for(env, key)
    first = native_handoff(env)
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    # Rehand off the approved generation but do not execute another unit.
    second = native_handoff(env)
    assert second.status is HandoffStatus.ACCEPTED
    before = native_snapshot(env)
    with pytest.raises(ValueError), env.database.connect() as conn:
        continue_coverage_command(conn, NAMESPACE, env.session, second.lease.fence, check(env))
    assert native_snapshot(env) == before and semantic_calls(env) == 1


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("part_count", [2])
@pytest.mark.parametrize(
    "damage",
    [
        "expected_digest",
        "accepted_count",
        "source_watermark",
        "missing",
        "checkpoint_without_proof",
    ],
)
def test_progress_approval_tamper_refuses_handoff_without_drift(native_worker, damage):
    from psycopg.types.json import Jsonb

    env = native_worker
    reply_for(env, expected_units(env.admission.contract, env.wire.records)[0])
    first = native_handoff(env)
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    with env.database.connect() as conn:
        row = conn.execute("SELECT coverage_proof FROM command_recovery_attempts").fetchone()
        proof = row["coverage_proof"]
        if damage == "expected_digest":
            proof[damage] = "f" * 64
        elif damage == "accepted_count":
            proof[damage] = 0
        elif damage == "source_watermark":
            proof[damage] = 0
        elif damage == "missing":
            proof = None
        else:
            conn.execute("UPDATE command_recovery_attempts SET reason='coverage_checkpoint'")
            proof = None
        conn.execute("UPDATE command_recovery_attempts SET coverage_proof=%s", (Jsonb(proof),))
    before = native_snapshot(env)
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.REQUIRES_RECONCILIATION and handoff.lease is None
    assert native_snapshot(env) == before and semantic_calls(env) == 1


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("part_count", [2])
def test_existing_settled_call_does_not_hide_next_part_full_c_shortfall(native_worker, monkeypatch):
    from copy import deepcopy

    env = native_worker
    reply_for(env, expected_units(env.admission.contract, env.wire.records)[0])
    first = native_handoff(env)
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    # The real authenticated loader receives this changed official-response
    # transport fixture, not a substituted verifier or fabricated ledger state.
    changed = deepcopy(METADATA)
    changed["data"][0]["context_window"] = CAPACITY * 2
    monkeypatch.setattr("tests.worker.test_coverage_dispatch.METADATA", changed)
    requests_before = len(env.native_requests)
    before = native_snapshot(env)
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.REQUIRES_RECONCILIATION and handoff.lease is None
    assert any(r.url.path == "/models" for r in env.native_requests[requests_before:])
    assert native_snapshot(env) == before and semantic_calls(env) == 1


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("part_count", [1])
def test_sixth_prebudget_crash_still_exhausts_five_crash_allowance(native_worker, monkeypatch):
    from agent_storage.postgres.coverage import PostgresCoverageStore

    class ProcessCrash(BaseException):
        pass

    env = native_worker
    reached = []

    def crash(self, binding, *, fence):
        reached.append(binding.run_id)
        raise ProcessCrash()

    with env.database.connect() as conn:
        created = conn.execute("SELECT created_at FROM session_command_pending").fetchone()
    for index in range(6):
        handoff = native_handoff(env)
        assert handoff.status is HandoffStatus.ACCEPTED
        with monkeypatch.context() as patch:
            patch.setattr(PostgresCoverageStore, "initialize_model_budget", crash)
            with pytest.raises(ProcessCrash):
                env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
        assert len(reached) == index + 1
        with env.database.connect() as conn:
            assert (
                conn.execute("SELECT created_at FROM session_command_pending").fetchone() == created
            )
            conn.execute("UPDATE session_command_pending SET recovery_due_at=clock_timestamp()")
            conn.execute(
                "UPDATE broker_outbox SET status='published',published_at=clock_timestamp()"
            )
        recovery = recover_command_batch(
            env.dsn, deployment_namespace=NAMESPACE, scope=env.scope, coverage_check=check(env)
        )
        assert len(recovery) == 1 and recovery[0].status is (
            RecoveryStatus.EXHAUSTED if index == 5 else RecoveryStatus.APPROVED
        )
    with env.database.connect() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM command_recovery_attempts").fetchone()["n"] == 5
        )
        assert not conn.execute(
            "SELECT 1 FROM coverage_model_ledger WHERE run_id=%s", (f"coverage-{env.session}",)
        ).fetchall()
    assert semantic_calls(env) == 0 and set(reached) == {f"coverage-{env.session}"}
