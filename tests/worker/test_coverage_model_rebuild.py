"""Authoritative recovery and report retention on actual fixture-owned PostgreSQL."""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID

import psycopg
import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    CoverageModelCheckpoint,
    decode_model_checkpoint,
)
from agent_core.domain.identifiers import ArtifactId
from agent_storage.postgres import coverage_model_acceptance as acceptance
from agent_storage.postgres import coverage_model_source as source
from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES

from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    check_authority,
    model_cloud,
)
from tests.worker.test_coverage_model_acceptance import (
    accepted,
    certify,
    database_state,
    history,
    report_for,
    settled,
)

MODEL = ("coverage_model_calls", "coverage_model_ledger", "coverage_model_events")
PROJECTIONS = (
    *MODEL,
    "coverage_runs",
    "coverage_units",
    "coverage_batches",
    "coverage_continuations",
)
DELETIONS = (*MODEL, "all_model", "all")


def projection_state(env):
    with psycopg.connect(env.dsn) as connection:
        return tuple(
            connection.execute(
                f"SELECT to_jsonb(t) FROM {table} t WHERE run_id=%s ORDER BY to_jsonb(t)::text",
                (env.binding.run_id,),
            ).fetchall()
            for table in PROJECTIONS
        )


def remove_projections(env, deletion):
    tables = PROJECTIONS if deletion == "all" else MODEL if deletion == "all_model" else (deletion,)
    with psycopg.connect(env.dsn) as connection:
        for table in tables:
            connection.execute(f"DELETE FROM {table} WHERE run_id=%s", (env.binding.run_id,))


def issued(env, monkeypatch, *, short_report=False):
    request, observation, merge, original_id = accepted(env)
    if short_report:
        deadline = datetime.now(UTC) + timedelta(seconds=75)
        original_publish = env.cloud.store_payload_immutable

        def publish(payload, *, artifact_id):
            if payload.kind == "coverage_report":
                payload = payload.model_copy(update={"retained_until": deadline})
            return original_publish(payload, artifact_id=artifact_id)

        monkeypatch.setattr(env.cloud, "store_payload_immutable", publish)
    else:
        deadline = env.binding.snapshot.expires_at
    ref, digest = report_for(env, (observation, merge))
    certificate = certify(env, ref, digest)
    return request, original_id, ref, certificate, deadline


@pytest.mark.parametrize("deletion", DELETIONS)
@pytest.mark.parametrize("certified", [False, True])
def test_rebuild_restores_each_and_all_projections_from_authoritative_proof(
    model_cloud,
    monkeypatch,
    deletion,
    certified,  # noqa: F811
):
    env = model_cloud
    if certified:
        request, _, ref, certificate, _ = issued(env, monkeypatch)
    else:
        request, _, _, _ = accepted(env)
    before, sources = projection_state(env), history(env)
    remove_projections(env, deletion)
    assert env.store.rebuild(env.binding.namespace, env.binding.run_id) == sources[-1].sequence
    assert projection_state(env) == before and history(env) == sources
    assert database_state(env)[0] == (1, 30, 0)
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (2, 2)
    env.store.commit(request, fence=env.fence)
    if certified:
        assert env.store.certificate(
            env.binding.namespace,
            env.binding.run_id,
            now=datetime.now(UTC),
            check_authority=lambda: check_authority(env),
        ) == (certificate, ref)
    assert len(env.requests) == 1


@pytest.mark.parametrize("deletion", DELETIONS)
@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_original_loss_never_partially_restores_projections(
    model_cloud,
    deletion,
    damage,  # noqa: F811
):
    env = model_cloud
    _, _, _, identifier = accepted(env)
    body = env.cloud.read_payload_bytes(identifier)
    key = next(key for key, item in env.client.objects.items() if item["Body"] == body)
    if damage == "missing":
        del env.client.objects[key]
    else:
        env.client.objects[key]["Body"] = b"corrupt original"
    remove_projections(env, deletion)
    before, sources = projection_state(env), history(env)
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert projection_state(env) == before and history(env) == sources and len(env.requests) == 1


def test_deleted_call_index_cannot_hide_original_volume_before_replay(
    model_cloud,
    monkeypatch,  # noqa: F811
):
    env = model_cloud
    _, _, _, identifier = accepted(env)
    remove_projections(env, "coverage_model_calls")
    with psycopg.connect(env.dsn) as connection:
        # Explicit corrupt native metadata for a preflight control, not lawful proof.
        connection.execute("SET LOCAL session_replication_role=replica")
        connection.execute(
            "UPDATE artifact_payload_metadata SET size_bytes=%s WHERE artifact_id=%s",
            (MAX_COVERAGE_ARTIFACT_BYTES + 1, identifier),
        )
    before, sources = projection_state(env), history(env)

    def forbidden(*args, **kwargs):
        raise AssertionError("unbounded authoritative replay preceded proof-volume preflight")

    monkeypatch.setattr(source, "verify_model_checkpoint", forbidden)
    with pytest.raises(ValueError, match="original proof exceeds cumulative read bound"):
        env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert projection_state(env) == before and history(env) == sources


def test_semantic_artifact_failure_rolls_back_tentative_model_reconstruction(
    model_cloud,
    monkeypatch,  # noqa: F811
):
    env = model_cloud
    accepted(env)
    remove_projections(env, "all_model")
    original_verify = acceptance.verify_results
    reached = False

    def refuse(*args, **kwargs):
        nonlocal reached
        # This batch gate runs only after the bounded original replay restores the model index.
        original_verify(*args, **kwargs)
        reached = True
        raise ValueError("test canonical observation proof unavailable")

    monkeypatch.setattr(acceptance, "verify_results", refuse)
    before, sources = projection_state(env), history(env)
    with pytest.raises(ValueError, match="observation proof unavailable"):
        env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert reached and projection_state(env) == before and history(env) == sources


@pytest.mark.parametrize("gate", ["certify", "query", "rebuild"])
@pytest.mark.parametrize("delete_calls", [False, True])
def test_shared_replay_caps_two_settled_originals_before_any_object_read(
    model_cloud, monkeypatch, gate, delete_calls
):
    env = model_cloud
    # Full private wire fixture, not generated tokens or native-scale evidence.
    env.reply["choices"][0]["message"]["reasoning_content"] = "r" * (17 * 1024 * 1024)
    _, identifier = settled(env)
    original = decode_model_checkpoint(env.cloud.read_payload_bytes(identifier))
    receipt = CoverageModelUsageReceipt.model_validate(database_state(env)[1][0][1])
    reservation = receipt.reservation.model_copy(update={"reservation_key": "cap-second-original"})
    env.store.reserve_model_call(env.binding, reservation, fence=env.fence)
    second = CoverageModelCheckpoint(
        env.binding, reservation, original.completion, original.request
    )
    env.cloud.store_payload_immutable(
        ArtifactPayloadWrite(
            session_id=env.session,
            kind=MODEL_CHECKPOINT_KIND,
            mime_type="application/json",
            payload=second.canonical_bytes,
            created_at=datetime.now(UTC),
            retained_until=env.binding.snapshot.expires_at,
        ),
        artifact_id=second.artifact_id,
    )
    # Seed an authentic pre-fix oversized settled history only during preparation.
    # Restore the production ceiling before any target certify/query/rebuild gate.
    with monkeypatch.context() as preparation:
        preparation.setattr(source, "MAX_COVERAGE_ARTIFACT_BYTES", 64 * 1024 * 1024)
        env.store.record_model_usage(
            env.binding,
            receipt.model_copy(
                update={
                    "reservation": reservation,
                    "checkpoint_ref": f"artifact://{second.artifact_id}",
                    "checkpoint_digest": second.digest,
                }
            ),
            fence=env.fence,
        )
    assert source.MAX_COVERAGE_ARTIFACT_BYTES == MAX_COVERAGE_ARTIFACT_BYTES
    assert database_state(env)[0] == (2, 60, 0) and len(env.requests) == 1
    with psycopg.connect(env.dsn) as connection:
        rows = connection.execute(
            "SELECT artifact_id,size_bytes,sha256 FROM artifact_payload_metadata "
            "WHERE kind=%s AND session_id=%s",
            (MODEL_CHECKPOINT_KIND, env.session),
        ).fetchall()
    assert len(rows) == len({row[2] for row in rows}) == 2
    assert all(17 * 1024 * 1024 < row[1] < 18 * 1024 * 1024 for row in rows)
    assert sum(row[1] for row in rows) > MAX_COVERAGE_ARTIFACT_BYTES
    ref, digest = report_for(env, ())
    if delete_calls:
        remove_projections(env, "coverage_model_calls")
    before, events = projection_state(env), history(env)
    originals, read_bytes = {row[0] for row in rows}, 0
    read = env.cloud.objects.read_version_verified

    def counted(expectation, version):
        nonlocal read_bytes
        body = read(expectation, version)
        if expectation.artifact_id in originals:
            read_bytes += len(body)
        return body

    monkeypatch.setattr(env.cloud.objects, "read_version_verified", counted)
    with pytest.raises(ValueError, match="original proof exceeds cumulative read bound"):
        if gate == "certify":
            certify(env, ref, digest)
        elif gate == "query":
            env.store.model_budget_state(env.binding)
        else:
            env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert read_bytes == 0
    assert projection_state(env) == before and history(env) == events and len(env.requests) == 1


def test_report_expiry_after_read_rolls_back_certified_reconstruction(
    model_cloud,
    monkeypatch,  # noqa: F811
):
    env = model_cloud
    _, _, _, _, deadline = issued(env, monkeypatch, short_report=True)
    remove_projections(env, "all_model")
    original_rebuild = env.store._rebuild_budget
    reached = False

    def delay(connection, binding):
        nonlocal reached
        original_rebuild(connection, binding)
        reached = True
        connection.execute(
            "SELECT pg_sleep(greatest(0,extract(epoch FROM "
            "(%s::timestamptz-clock_timestamp())))+0.03)",
            (deadline,),
        )

    monkeypatch.setattr(env.store, "_rebuild_budget", delay)
    before, sources = projection_state(env), history(env)
    with pytest.raises(ValueError, match="retention expired"):
        env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert reached and datetime.now(UTC) >= deadline
    assert projection_state(env) == before and history(env) == sources and len(env.requests) == 1


def test_report_pin_blocks_concurrent_prune_until_certified_rebuild_rollback(
    model_cloud,
    monkeypatch,  # noqa: F811
):
    env = model_cloud
    _, _, ref, _, _ = issued(env, monkeypatch)
    identifier = ArtifactId(UUID(ref.removeprefix("artifact://")))
    remove_projections(env, "coverage_model_calls")
    original_rebuild = env.store._rebuild_budget
    entered, release = Event(), Event()

    def abort(connection, binding):
        original_rebuild(connection, binding)
        entered.set()
        assert release.wait(20)
        raise ValueError("test certified rebuild aborted after report pin")

    monkeypatch.setattr(env.store, "_rebuild_budget", abort)
    before, sources = projection_state(env), history(env)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(env.store.rebuild, env.binding.namespace, env.binding.run_id)
        try:
            assert entered.wait(60)
            with psycopg.connect(env.dsn) as connection:
                connection.execute("SET LOCAL lock_timeout='150ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    connection.execute(
                        "UPDATE artifact_payload_metadata SET lifecycle_status='pruned',"
                        "lifecycle_revision=4,pruning_at=clock_timestamp(),"
                        "pruned_at=clock_timestamp() WHERE artifact_id=%s",
                        (identifier,),
                    )
        finally:
            release.set()
        with pytest.raises(ValueError, match="aborted after report pin"):
            future.result(timeout=20)
    assert projection_state(env) == before and history(env) == sources


def test_report_prune_before_pin_refuses_and_rolls_back_certified_rebuild(
    model_cloud,
    monkeypatch,  # noqa: F811
):
    env = model_cloud
    _, _, ref, _, _ = issued(env, monkeypatch)
    identifier = ArtifactId(UUID(ref.removeprefix("artifact://")))
    remove_projections(env, "all_model")
    original_replay = env.store._replay_certificate
    reached = False

    def prune(connection, binding, event, **kwargs):
        nonlocal reached
        with psycopg.connect(env.dsn) as other:
            other.execute("SET LOCAL lock_timeout='1s'")
            other.execute(
                "UPDATE artifact_payload_metadata SET lifecycle_status='pruned',"
                "lifecycle_revision=4,pruning_at=clock_timestamp(),"
                "pruned_at=clock_timestamp() WHERE artifact_id=%s",
                (identifier,),
            )
        reached = True
        return original_replay(connection, binding, event, **kwargs)

    monkeypatch.setattr(env.store, "_replay_certificate", prune)
    before, sources = projection_state(env), history(env)
    with pytest.raises(ValueError, match="unavailable|lifecycle"):
        env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert reached and projection_state(env) == before and history(env) == sources
