"""Measured actual Worker/PG continuation; Host/model/S3 are controlled transports.

This is not live provider, broker, multi-process, browser or semantic acceptance.
"""
# ruff: noqa: F811

import cProfile
import json
from datetime import timedelta
from time import perf_counter

import psycopg
import pytest
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus

from tests.worker.coverage_model_cloud_fixtures import dsn, postgres_dsn  # noqa: F401
from tests.worker.test_coverage_dispatch import (  # noqa: F401
    _stop_native_capability,
    native_handoff,
    native_worker,
)
from tests.worker.test_coverage_multipart import (  # noqa: F401
    model_cloud,
    reply_for,
    semantic_calls,
)


@pytest.fixture(params=[1, 6, 9])
def part_count(request):
    return request.param


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
def test_worker_load_converges_with_exact_progress(
    native_worker, part_count, record_property, monkeypatch
):
    env = native_worker
    keys = expected_units(env.admission.contract, env.wire.records)
    assert len(keys) == 2 * part_count
    fixture_gets = sum(method == "get_object" for method, _ in env.client.calls)
    connect = psycopg.connect
    execute = psycopg.Connection.execute
    physical_connections = 0
    database_queries = 0
    from zebra_agent_worker import coverage_recovery as recovery

    verifier = recovery._ModelVerification
    recovery_check = recovery.verify_cloud_coverage_recovery
    proof_constructions = 0
    proof_phases = []

    def counted_verifier(*args, **kwargs):
        nonlocal proof_constructions
        proof_constructions += 1
        return verifier(*args, **kwargs)

    def counted_recovery(*args, **kwargs):
        before = proof_constructions
        try:
            return recovery_check(*args, **kwargs)
        finally:
            count = proof_constructions - before
            proof_phases.append(count)
            assert count <= 1, "recovery rescanned the model ledger for each accepted batch"

    def counted_execute(self, *args, **kwargs):
        nonlocal database_queries
        database_queries += 1
        return execute(self, *args, **kwargs)

    def counted_connect(*args, **kwargs):
        nonlocal physical_connections
        physical_connections += 1
        return connect(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", counted_connect)
    monkeypatch.setattr(psycopg.Connection, "execute", counted_execute)
    monkeypatch.setattr(recovery, "_ModelVerification", counted_verifier)
    monkeypatch.setattr(recovery, "verify_cloud_coverage_recovery", counted_recovery)
    started = perf_counter()  # Fixture admission/setup excluded explicitly.
    handoff_seconds, execution_seconds, object_gets = [], [], []
    first_progress_seconds = None
    result = None
    profile = cProfile.Profile()
    if part_count == 1:
        profile.enable()
    try:
        for index, key in enumerate(keys):
            reply_for(env, key)
            before = perf_counter()
            # Callback fixture has no process heartbeat. Use a fresh native consumer
            # per wake, proving replacement routing rather than extending its TTL.
            _stop_native_capability(env, remove_revoked=True)
            handoff = native_handoff(env)
            handoff_seconds.append(perf_counter() - before)
            assert handoff.status is HandoffStatus.ACCEPTED
            before = perf_counter()
            result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
            execution_seconds.append(perf_counter() - before)
            object_gets.append(
                sum(method == "get_object" for method, _ in env.client.calls) - fixture_gets
            )
            assert result.session.status is (
                SessionStatus.COMPLETED if index == len(keys) - 1 else SessionStatus.RUNNING
            )
            if first_progress_seconds is None:
                first_progress_seconds = perf_counter() - started
    except BaseException as error:
        record_property(
            "coverage_worker_failure",
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "records": len(env.wire.records),
                    "parts": part_count,
                    "expected_units": len(keys),
                    "runtime_budget_seconds": env.admission.max_runtime_seconds,
                    "session_status": None if result is None else result.session.status.value,
                    "coverage_refusal_reason": None
                    if result is None
                    else result.attempt_result.metadata.get("coverage_refusal_reason"),
                    "completed_callbacks": len(execution_seconds),
                    "elapsed_seconds": perf_counter() - started,
                    "physical_connections": physical_connections,
                    "database_queries": database_queries,
                    "live_e2e": False,
                }
            ),
        )
        raise
    finally:
        profile.disable()
    elapsed = perf_counter() - started
    measured_connections = physical_connections
    measured_queries = database_queries
    assert proof_phases and proof_constructions > 0
    with env.database.connect() as conn:
        rows = conn.execute(
            "SELECT coverage_proof FROM command_recovery_attempts ORDER BY wake_generation"
        ).fetchall()
        assert [r["coverage_proof"]["accepted_count"] for r in rows] == list(range(1, len(keys)))
        assert len({r["coverage_proof"]["expected_digest"] for r in rows}) == 1
    events = env.events.list_for_session(env.session)
    assert sum(e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in events) == 1
    assert semantic_calls(env) == part_count
    measurement = {
        "evidence": "actual_worker_postgres_controlled_host_model_s3",
        "boundary": "after_fixture_admission_before_first_handoff_to_certified_completion",
        "consumer_mode": "fresh_native_consumer_per_wake_no_process_heartbeat_fixture",
        "parts": part_count,
        "records": len(env.wire.records),
        "expected_units": len(keys),
        "model_http_calls": semantic_calls(env),
        "physical_connections": measured_connections,
        "database_queries": measured_queries,
        "recovery_proof_constructions_per_phase": proof_phases,
        "first_completed_unit_seconds": first_progress_seconds,
        "certified_completion_seconds": elapsed,
        "handoff_seconds": handoff_seconds,
        "execution_seconds": execution_seconds,
        "cumulative_object_gets": object_gets,
        "fixture_object_gets_excluded": fixture_gets,
        "profile_enabled": part_count == 1,
        "live_e2e": False,
        "business_accuracy_claim": False,
    }
    record_property("coverage_worker_measurement", json.dumps(measurement))
    print(json.dumps(measurement))
    if part_count == 1:
        import pstats

        pstats.Stats(profile).sort_stats("cumulative").print_stats(30)


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("part_count", [12], indirect=True)
def test_worker_full_context_budget_refuses_12_before_model(native_worker):
    env = native_worker
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.ACCEPTED
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.FAILED
    assert result.attempt_result.metadata["coverage_refusal_reason"] == "budget_exceeded"
    assert semantic_calls(env) == 0
    assert not any(e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in result.events)


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("part_count", [1], indirect=True)
@pytest.mark.parametrize("damage", ["bytes", "delete"])
def test_prepared_body_reuse_never_replaces_final_physical_reread(
    native_worker, monkeypatch, damage
):
    from dataclasses import replace

    from agent_core.domain.artifact_objects import (
        ArtifactObjectIntegrityError,
        ArtifactObjectNotFoundError,
    )
    from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck

    env = native_worker
    prepare = NativeCoverageRecoveryCheck.prepare
    mutated = []

    def damaged_final(checker, *args):
        proof = prepare(checker, *args)
        if not hasattr(proof, "final_authority"):
            return proof
        final = proof.final_authority

        def verify(deadline):
            original = next(params for method, params in reversed(env.client.calls)
                            if method == "get_object")
            key = original["Key"]
            if damage == "delete":
                del env.client.objects[key]
            else:
                body = env.client.objects[key]["Body"]
                env.client.objects[key]["Body"] = bytes([body[0] ^ 1]) + body[1:]
            offset = len(env.client.calls)
            try:
                final(deadline)
            finally:
                matches = [params for method, params in env.client.calls[offset:]
                           if method == "get_object" and params["Key"] == key
                           and params.get("VersionId") == original.get("VersionId")]
                assert matches, "final authority did not reread the damaged physical version"
                mutated.append(key)

        return replace(proof, final_authority=verify)

    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.ACCEPTED
    monkeypatch.setattr(NativeCoverageRecoveryCheck, "prepare", damaged_final)
    reply_for(env, expected_units(env.admission.contract, env.wire.records)[0])
    # This low-level Worker entrypoint propagates physical proof errors; the
    # command consumer owns terminal/reconciliation routing, not this checker.
    error = ArtifactObjectIntegrityError if damage == "bytes" else ArtifactObjectNotFoundError
    with pytest.raises(error):
        env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert mutated
    assert semantic_calls(env) == 1
    with env.database.connect() as connection:
        assert not connection.execute("SELECT 1 FROM command_recovery_attempts").fetchall()
    assert not any(e.event_type is EventType.COVERAGE_REPORT_CERTIFIED
                   for e in env.events.list_for_session(env.session))


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("part_count", [1], indirect=True)
@pytest.mark.parametrize(
    "boundary,reason",
    [
        ("runtime", "budget_exceeded"),
        ("grant", "authority_invalid"),
        ("grant_race", "authority_invalid"),
    ],
)
def test_worker_expiry_has_typed_terminal_without_model(
    native_worker, monkeypatch, boundary, reason
):
    import zebra_agent_worker.coverage_dispatch as dispatch

    env = native_worker
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.ACCEPTED
    expired = (
        env.now + timedelta(seconds=env.admission.max_runtime_seconds + 5)
        if boundary == "runtime"
        else env.host.expires_at + timedelta(seconds=5)
    )

    class Clock:
        calls = 0

        @staticmethod
        def now(tz):
            Clock.calls += 1
            if boundary == "grant_race" and Clock.calls == 1:
                return env.host.expires_at - timedelta(microseconds=1)
            return expired

    monkeypatch.setattr(dispatch, "datetime", Clock)
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.FAILED
    assert result.attempt_result.metadata["coverage_refusal_reason"] == reason
    assert semantic_calls(env) == 0
    assert not any(e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in result.events)
