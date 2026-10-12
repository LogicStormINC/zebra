"""Physical proof stays proportional to the affected refs, not historical run objects."""
# ruff: noqa: F811 - imported pytest fixtures

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.application.coverage_checks import merge_observations
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.identifiers import ArtifactId

from tests.agent_storage.test_coverage_evidence_operation import (  # noqa: F401
    acceptance,
    checkpoint,
    dsn,
    evidence,
    metadata,
    model_cloud,
    operation,
    postgres_dsn,
    snapshot,
)
from tests.worker.coverage_model_cloud_fixtures import authority
from tests.worker.test_coverage_model_acceptance import request_for


def test_unrelated_finalized_run_objects_do_not_expand_get_or_metadata_scope(evidence, monkeypatch):
    env = evidence
    owner = operation(env)
    checkpoint(env, owner)
    request, payloads = acceptance(env)
    owner.commit_evidence(env.binding, request, payloads, fence=env.fence)
    from zebra_agent_worker import coverage_prepared_reads as module

    reads, pages = [], []
    original_read = env.objects.read_version_verified
    original_metadata = module.metadata_batch

    def read(expectation, version):
        reads.append(expectation.artifact_id)
        return original_read(expectation, version)

    def page(source, identifiers):
        pages.append(tuple(identifiers))
        return original_metadata(source, identifiers)

    monkeypatch.setattr(env.objects, "read_version_verified", read)
    monkeypatch.setattr(module, "metadata_batch", page)
    owner.commit_evidence(env.binding, request, payloads, fence=env.fence)
    baseline = tuple(reads), tuple(pages)
    # Publish real immutable metadata/receipts/Events in two bounded batches.
    # None are referenced by this operation's model calls, units or accepted batches.
    unrelated = set()
    with monkeypatch.context() as patch:
        patch.setattr(env.objects, "read_version_verified", original_read)
        for _ in range(2):
            writes = tuple((ArtifactId(uuid4()), ArtifactPayloadWrite(
                session_id=env.session, kind="unrelated-run-evidence",
                mime_type="application/octet-stream", payload=b"unrelated",
                created_at=datetime.now(UTC), retained_until=env.binding.snapshot.expires_at,
            )) for _ in range(501))
            unrelated.update(identifier for identifier, _ in writes)
            env.cloud.publisher.publish_batch(
                env.binding, writes, authority=authority(env), check_authority=lambda: None,
            )
    reads.clear()
    pages.clear()
    owner.commit_evidence(env.binding, request, payloads, fence=env.fence)
    assert (tuple(reads), tuple(pages)) == baseline
    assert not unrelated.intersection(reads)
    assert not unrelated.intersection(identifier for page in pages for identifier in page)


def test_record_merge_collects_prior_batches_parts_and_observations(evidence):
    env = evidence
    owner = operation(env)
    checkpoint(env, owner)
    request, payloads = acceptance(env)
    owner.commit_evidence(env.binding, request, payloads, fence=env.fence)
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    observation = derive_semantic_observation(
        env.payload.payload, env.receipt, env.definition, env.key, env.record,
    )
    key = next(item for item in expected_units(env.binding.contract, (env.record,))
               if item.kind == "record_merge")
    merge = merge_observations(key, tuple(part.id for part in env.record.parts), (observation,))
    # Capture the existing producer's actual writes; keep its canonical result shape.
    writes = []
    original = env.cloud.store_payload_immutable

    def capture(payload, *, artifact_id):
        writes.append((artifact_id, payload))
        # Only prepare metadata; the coordinator performs the actual publication.
        return env.cloud._stored(metadata(env, env.checkpoint.artifact_id)).model_copy(update={
            "artifact_id": artifact_id, "uri": f"artifact://{artifact_id}",
        })

    env.cloud.store_payload_immutable = capture
    try:
        merged_request = request_for(env, merge)
    finally:
        env.cloud.store_payload_immutable = original
    result = owner.commit_evidence(env.binding, merged_request, tuple(writes), fence=env.fence)
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (2, 2)
    assert owner.commit_evidence(
        env.binding, merged_request, tuple(writes), fence=env.fence,
    ) == result


def test_successful_owner_seeds_exact_records_but_not_failed_owner(evidence, monkeypatch):
    env = evidence
    env.cloud.reuse_verified_payloads = True
    owner = operation(env)
    from agent_storage.postgres import coverage_model_budget as module

    original = module.project_watermark

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("after usage")

    with monkeypatch.context() as patch:
        patch.setattr(module, "project_watermark", crash)
        with pytest.raises(RuntimeError, match="after usage"):
            checkpoint(env, owner)
    identifier = env.checkpoint.artifact_id
    assert identifier not in env.cloud._verified_payloads
    checkpoint(env, owner)
    assert env.cloud._verified_payloads[identifier] == (metadata(env), env.payload.payload)
    reads = []
    get = env.objects.read_version_verified

    def read(*args, **kwargs):
        reads.append(True)
        return get(*args, **kwargs)

    monkeypatch.setattr(env.objects, "read_version_verified", read)
    # Preserve the mandatory post-semantic read; its fresh exact metadata matches the owner cache.
    assert env.cloud.read_payload_bytes(identifier) == env.payload.payload
    assert not reads
    # Independent final scope gets a fresh byte owner and actually reads the original.
    with env.database.connect() as connection, env.cloud._locked_proof_scope(
        connection, env.cloud.deployment, env.binding,
        derive=env.store._model_observation_deriver, final_certification=True,
    ) as reader:
        assert reader.read_payload_bytes(identifier) == env.payload.payload
    assert reads == [True]


def test_foreign_cache_callback_refuses_before_staging(evidence, monkeypatch):
    env = evidence
    before = len(env.client.objects)
    monkeypatch.setattr(env.cloud, "_remember_publication", lambda *args: None)
    with pytest.raises(ValueError, match="altered evidence source"):
        checkpoint(env)
    assert metadata(env) is None and len(env.client.objects) == before


def test_retention_expiring_in_last_native_read_rolls_back_before_ack(evidence, monkeypatch):
    env = evidence
    from agent_storage.postgres import coverage_evidence_operation as module

    deadline = datetime.now(UTC) + timedelta(seconds=3)
    env.payload = env.payload.model_copy(update={"retained_until": deadline})
    indexed = module.indexed_state
    delayed = []

    def late(connection, deployment, binding):
        state = indexed(connection, deployment, binding)
        connection.execute(
            "SELECT pg_sleep(greatest(0,extract(epoch FROM "
            "(%s::timestamptz-clock_timestamp())))+0.01)", (deadline,),
        )
        delayed.append(True)
        return state

    monkeypatch.setattr(module, "indexed_state", late)
    before = snapshot(env)
    with pytest.raises(ValueError, match="retention expired"):
        checkpoint(env)
    assert delayed == [True] and snapshot(env) == before
    assert metadata(env).lifecycle_revision == 0
