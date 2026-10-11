"""Actual PG candidate accounting; provider/Host/S3 transports are explicit fixtures."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from agent_core.application.coverage_checks import merge_observations
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadNotFoundError
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseLostError
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres import coverage_model_budget as budget
from agent_storage.postgres import coverage_model_source as source
from agent_storage.postgres.coverage_transactions import lock_run

from tests.agent_integrations.test_coverage_model_invocation import invoke
from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    CAPACITY,
    NAMESPACE,
    check_authority,
    compose,
    dsn,
    model_cloud,
    postgres_dsn,
)
from tests.worker.test_coverage_model_acceptance import (  # noqa: F401
    configured,
    multipart_cloud,
    report_for,
    request_for,
)
from tests.worker.test_coverage_model_cloud import database_state


@pytest.fixture
def candidate_env(multipart_cloud):  # noqa: F811
    env = multipart_cloud
    env.component = compose(env)
    env.part_keys = tuple(
        key for key in expected_units(env.binding.contract, (env.record,)) if key.kind == "part"
    )
    env.calls_before = len(env.requests)
    return env


def select_part(env, index, *, reasoning_bytes=0):
    env.key = env.part_keys[index]
    message = env.reply["choices"][0]["message"]
    message["reasoning_content"] = "x" * reasoning_bytes
    message["content"] = json.dumps(
        {"key": env.key.model_dump(mode="json"), "outcome": "clear", "categories": [], "quotes": []}
    )


def settled_first(env, *, reasoning_bytes=0):
    select_part(env, 0, reasoning_bytes=reasoning_bytes)
    invoke(env, env.component)
    return next(
        CoverageModelUsageReceipt.model_validate(row[1])
        for row in database_state(env)[1]
        if row[1] is not None
    )


def stage_candidate(env, monkeypatch, *, reasoning_bytes=0):
    """Stop only after the actual component publishes its governed v2 original."""
    select_part(env, 1, reasoning_bytes=reasoning_bytes)
    captured = []

    def hold(binding, receipt, *, fence):
        captured.append(receipt)
        raise ValueError("fixture stops before usage settlement")

    with monkeypatch.context() as patch:
        patch.setattr(env.store, "record_model_usage", hold)
        with pytest.raises(CoverageRefusedError):
            invoke(env, env.component)
    assert len(captured) == 1, "candidate settlement hook was not reached"
    assert len(env.requests) - env.calls_before == 2
    return captured[0]


def snapshot(env):
    # Return only fingerprints: no payload, provider reasoning or credentials in
    # a failure assertion. Includes source Events, projections and lifecycle rows.
    with env.database.connect() as conn:
        return {
            table: conn.execute(
                "SELECT md5(coalesce(jsonb_agg(to_jsonb(t) "
                "ORDER BY to_jsonb(t)::text)::text,'[]')) "
                f"AS digest FROM {table} t"
            ).fetchone()["digest"]
            for table in (
                "session_events",
                "coverage_model_events",
                "coverage_model_ledger",
                "coverage_model_calls",
                "coverage_runs",
                "coverage_units",
                "artifact_payload_metadata",
                "artifact_payload_mutations",
                "artifact_payload_management_audit",
                "worker_leases",
            )
        }


def track_reads(env, monkeypatch):
    reads = []
    original = env.objects.read_version_verified

    def read(expectation, version):
        reads.append(expectation.size_bytes)
        return original(expectation, version)

    monkeypatch.setattr(env.objects, "read_version_verified", read)
    return reads


def receipt_size(env, receipt):
    with env.database.connect() as conn:
        return conn.execute(
            "SELECT size_bytes FROM artifact_payload_metadata WHERE artifact_id=%s",
            (UUID(receipt.checkpoint_ref.removeprefix("artifact://")),),
        ).fetchone()["size_bytes"]


def action(env, mode, first, candidate=None):
    if mode == "settle":
        return env.store.record_model_usage(env.binding, candidate, fence=env.fence)
    if mode == "reserve":
        reservation = first.reservation.model_copy(
            update={
                "key": env.part_keys[1],
                "reservation_key": "candidate-next",
                "request_digest": "a" * 64,
            }
        )
        return env.store.reserve_model_call(env.binding, reservation, fence=env.fence)
    return env.store.model_budget_state(env.binding)


def test_actual_32mib_candidate_refuses_before_reads_or_refund(candidate_env, monkeypatch):
    env = candidate_env
    first = settled_first(env, reasoning_bytes=17 * 1024 * 1024)
    candidate = stage_candidate(env, monkeypatch, reasoning_bytes=17 * 1024 * 1024)
    assert receipt_size(env, first) + receipt_size(env, candidate) > 32 * 1024 * 1024
    assert max(receipt_size(env, first), receipt_size(env, candidate)) < 32 * 1024 * 1024
    state = database_state(env)
    assert state[0] == (2, CAPACITY + first.total_tokens, 1)
    before = snapshot(env)
    reads = track_reads(env, monkeypatch)
    with pytest.raises(ValueError, match="cumulative read bound"):
        action(env, "settle", first, candidate)
    assert reads == [] and snapshot(env) == before and database_state(env) == state
    assert len(env.requests) - env.calls_before == 2


@pytest.mark.parametrize("mode", ["reserve", "replay"])
def test_prior_set_preflight_precedes_every_original_read(candidate_env, monkeypatch, mode):
    env = candidate_env
    first = settled_first(env, reasoning_bytes=128 * 1024)
    monkeypatch.setattr(source, "MAX_COVERAGE_ARTIFACT_BYTES", receipt_size(env, first) - 1)
    before = snapshot(env)
    reads = track_reads(env, monkeypatch)
    with pytest.raises(ValueError, match="cumulative read bound"):
        action(env, mode, first)
    assert reads == [] and snapshot(env) == before
    assert len(env.requests) - env.calls_before == 1


@pytest.mark.parametrize("mode", ["reserve", "settle", "replay"])
@pytest.mark.parametrize("damage", ["missing", "size", "pruning", "expired"])
def test_missing_or_conflicting_metadata_refuses_before_reads(
    candidate_env, monkeypatch, mode, damage
):
    env = candidate_env
    first = settled_first(env)
    candidate = stage_candidate(env, monkeypatch) if mode == "settle" else None
    target = candidate or first
    identifier = UUID(target.checkpoint_ref.removeprefix("artifact://"))
    with env.database.connect() as conn:
        if damage == "missing":
            # Remove only this fixture original's dependent lifecycle records;
            # the authoritative usage/reservation/materialization Events remain.
            for table in ("artifact_payload_mutations", "artifact_payload_management_audit"):
                conn.execute(f"DELETE FROM {table} WHERE artifact_id=%s", (identifier,))
            conn.execute(
                "DELETE FROM artifact_payload_metadata WHERE artifact_id=%s", (identifier,)
            )
        elif damage == "size":
            conn.execute(
                "UPDATE artifact_payload_metadata SET size_bytes=size_bytes+1 WHERE artifact_id=%s",
                (identifier,),
            )
        elif damage == "pruning":
            conn.execute(
                "UPDATE artifact_payload_metadata SET lifecycle_status='pruning',"
                "lifecycle_revision=3,"
                "pruning_at=clock_timestamp() WHERE artifact_id=%s",
                (identifier,),
            )
        else:
            conn.execute(
                "UPDATE artifact_payload_metadata SET retained_until=clock_timestamp() "
                "WHERE artifact_id=%s",
                (identifier,),
            )
    before = snapshot(env)
    reads = track_reads(env, monkeypatch)
    error = (
        CloudArtifactPayloadNotFoundError
        if damage == "missing" and mode == "settle"
        else ValueError
    )
    with pytest.raises(error):
        action(env, mode, first, candidate)
    assert reads == [] and snapshot(env) == before
    assert len(env.requests) - env.calls_before == (2 if candidate is not None else 1)


@pytest.mark.parametrize("mode", ["reserve", "settle", "replay"])
def test_missing_reserved_source_refuses_before_objects(candidate_env, monkeypatch, mode):
    env = candidate_env
    first = settled_first(env)
    candidate = stage_candidate(env, monkeypatch) if mode == "settle" else None
    with env.database.connect() as conn:
        conn.execute(
            "DELETE FROM session_events WHERE event_type='coverage_model_call_reserved' "
            "AND payload->'reservation'->>'reservation_key'=%s",
            (first.reservation.reservation_key,),
        )
    before = snapshot(env)
    reads = track_reads(env, monkeypatch)
    with pytest.raises(ValueError):
        action(env, mode, first, candidate)
    # Exercise the shared LEFT JOIN guard itself, not only the enclosing
    # Task-history/witness refusal caused by the missing reserved Event.
    with env.database.connect() as conn:
        lock_run(conn, NAMESPACE, env.binding, env.fence)
        with pytest.raises(ValueError, match="source"):
            source.preflight_original_volume(conn, NAMESPACE, env.binding)
    assert reads == [] and snapshot(env) == before


@pytest.mark.parametrize("mode", ["reserve", "settle"])
def test_stale_native_fence_refuses_without_reads_or_accounting(candidate_env, monkeypatch, mode):
    env = candidate_env
    first = settled_first(env)
    candidate = stage_candidate(env, monkeypatch) if mode == "settle" else None
    old = env.fence
    env.leases.release(env.session, fence=old)
    env.leases.acquire(
        env.session, owner_instance_id="candidate-replacement", ttl=timedelta(minutes=5)
    )
    before = snapshot(env)
    reads = track_reads(env, monkeypatch)
    with pytest.raises(LeaseLostError):
        action(env, mode, first, candidate)
    assert reads == [] and snapshot(env) == before


def test_within_bound_multipart_and_exact_retries_count_originals_once(candidate_env, monkeypatch):
    env = candidate_env
    first = settled_first(env, reasoning_bytes=128 * 1024)
    candidate = stage_candidate(env, monkeypatch, reasoning_bytes=128 * 1024)
    bound = receipt_size(env, first) + receipt_size(env, candidate)
    preflight = source.preflight_original_volume
    gates = []

    def reached(connection, deployment, binding, **kwargs):
        volume = connection.execute(
            "SELECT coalesce(sum(octet_length(to_jsonb(e)::text)),0) AS bytes "
            "FROM session_events e WHERE deployment_namespace=%s AND session_id=%s "
            "AND payload->>'namespace'=%s AND payload->>'run_id'=%s AND event_type=ANY(%s)",
            (
                deployment,
                binding.session_id,
                binding.namespace,
                binding.run_id,
                list(source.MODEL_TYPES),
            ),
        ).fetchone()["bytes"]
        assert volume < bound, "source Event volume must not mask the original-set ceiling"
        preflight(connection, deployment, binding, **kwargs)
        gates.append(kwargs.get("candidate"))

    monkeypatch.setattr(source, "preflight_original_volume", reached)
    monkeypatch.setattr(budget, "preflight_original_volume", reached)
    monkeypatch.setattr(source, "MAX_COVERAGE_ARTIFACT_BYTES", bound)
    env.store.record_model_usage(env.binding, candidate, fence=env.fence)
    assert database_state(env)[0] == (2, first.total_tokens + candidate.total_tokens, 0)
    before = snapshot(env)
    assert (
        env.store.reserve_model_call(env.binding, candidate.reservation, fence=env.fence).invoke
        is False
    )
    env.store.record_model_usage(env.binding, candidate, fence=env.fence)
    assert snapshot(env) == before
    assert env.store.model_budget_state(env.binding).unresolved == 0
    assert gates == [candidate, None, candidate, None], "all four volume gates must complete"
    # Release the small test ceiling before adding truthful acceptance descriptors;
    # the actual originals remain below the production 32 MiB cap throughout.
    monkeypatch.setattr(source, "MAX_COVERAGE_ARTIFACT_BYTES", 32 * 1024 * 1024)
    configured(env)
    observations = []
    for receipt in (first, candidate):
        body = env.cloud.read_payload_bytes(ArtifactId(UUID(receipt.checkpoint_ref[11:])))
        observation = derive_semantic_observation(
            body, receipt, env.definition, receipt.reservation.key, env.record
        )
        env.store.commit(request_for(env, observation), fence=env.fence)
        observations.append(observation)
    merge_key = next(
        k for k in expected_units(env.binding.contract, (env.record,)) if k.kind == "record_merge"
    )
    merge = merge_observations(
        merge_key, tuple(part.id for part in env.record.parts), tuple(observations)
    )
    env.store.commit(request_for(env, merge), fence=env.fence)
    ref, digest = report_for(env, (*observations, merge))
    certificate = env.store.certify(
        env.binding.namespace,
        env.binding.run_id,
        report_ref=ref,
        report_digest=digest,
        fence=env.fence,
        check_authority=lambda: check_authority(env),
    )
    assert certificate.processed_units == 3 and certificate.read_parts == 2
    assert env.store.certificate(
        env.binding.namespace,
        env.binding.run_id,
        now=datetime.now(UTC),
        check_authority=lambda: check_authority(env),
    ) == (certificate, ref)
    assert len(env.requests) - env.calls_before == 2
