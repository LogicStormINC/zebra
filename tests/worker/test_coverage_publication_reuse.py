"""Published bytes reuse is bounded and never substitutes current authority or final proof."""
# ruff: noqa: F401,F811

from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.leases import LeaseLostError
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres import coverage_artifact_publication as publication_module

from tests.agent_storage.test_coverage_artifact_batches import metadata, writes
from tests.agent_storage.test_coverage_artifact_publication import _replace_worker
from tests.agent_storage.test_postgres_coverage import source_counts
from tests.worker.test_coverage_prepared_reads import (
    NAMESPACE,
    dsn,
    facade,
    postgres_dsn,
    postgres_env,
    publication,
)


@pytest.mark.parametrize("batch", [False, True])
def test_native_publication_reuses_bytes_but_final_proof_reads_objects(
    publication, monkeypatch, batch,
):
    env, source = publication, facade(publication)
    source.reuse_verified_payloads = True
    payloads = writes(env, 2 if batch else 1)
    read = Mock(wraps=env.objects.read_version_verified)
    monkeypatch.setattr(env.objects, "read_version_verified", read)
    if batch:
        stored = source.store_payloads_immutable(payloads)
    else:
        identifier, payload = payloads[0]
        stored = (source.store_payload_immutable(payload, artifact_id=identifier),)
    assert read.call_count == len(payloads)  # Native publication verifies each actual object.
    for record, (_, payload) in zip(stored, payloads, strict=True):
        assert source.read_payload_bytes(record.artifact_id) == payload.payload
    assert read.call_count == len(payloads)  # Fresh metadata, no second physical download.
    with env.metadata._database.connect() as connection:
        with source._locked_proof_scope(
            connection, NAMESPACE, env.binding, final_certification=True,
            derive=derive_semantic_observation,
        ) as reader:
            for record, (_, payload) in zip(stored, payloads, strict=True):
                assert reader.read_payload_bytes(record.artifact_id) == payload.payload
    assert read.call_count == 2 * len(payloads)  # Independent final proof bypasses reuse.


@pytest.mark.parametrize("change", ["metadata", "revocation", "publisher"])
def test_publication_reuse_never_hides_changed_record_or_authority(
    publication, monkeypatch, change,
):
    env, source = publication, facade(publication)
    source.reuse_verified_payloads = True
    identifier, payload = writes(env, 1)[0]
    if change == "publisher":
        publish = source.publisher.publish_batch
        monkeypatch.setattr(source.publisher, "publish_batch", lambda *a, **k: publish(*a, **k))
    source.store_payload_immutable(payload, artifact_id=identifier)
    read = Mock(wraps=env.objects.read_version_verified)
    monkeypatch.setattr(env.objects, "read_version_verified", read)
    if change == "revocation":
        source.check_authority = Mock(side_effect=ValueError("revoked"))
        with pytest.raises(ValueError, match="revoked"):
            source.read_payload_bytes(identifier)
        read.assert_not_called()
        return
    if change == "metadata":
        with env.metadata._database.connect() as connection:
            connection.execute(
                "UPDATE artifact_payload_metadata SET file_name='changed' "
                "WHERE deployment_namespace=%s AND artifact_id=%s", (NAMESPACE, identifier),
            )
    assert source.read_payload_bytes(identifier) == payload.payload
    assert read.call_count == 1  # Changed record/delegate does not inherit publication reuse.


def test_publication_reuse_has_bounded_identity_count(publication):
    env, source = publication, facade(publication)
    source.reuse_verified_payloads = True
    identifier, payload = writes(env, 1)[0]
    source.store_payload_immutable(payload, artifact_id=identifier)
    record, body = source._verified_payloads[identifier]
    for _ in range(256):
        # Record identity is derived from its reservation, not a top-level field.
        source._remember_verified(record.model_copy(update={
            "reservation": record.reservation.model_copy(update={"artifact_id": uuid4()}),
        }), body)
    assert len(source._verified_payloads) == 256
    assert identifier not in source._verified_payloads
    assert source._verified_bytes == sum(
        len(body) for _, body in source._verified_payloads.values()
    )


@pytest.mark.parametrize("batch", [False, True])
def test_postsync_revocation_seeds_no_publication_bytes(publication, monkeypatch, batch):
    env, source = publication, facade(publication)
    source.reuse_verified_payloads = True
    payloads = writes(env, 2 if batch else 1)
    before, syncs = source_counts(env), 0
    read = Mock(wraps=env.objects.read_version_verified)
    monkeypatch.setattr(env.objects, "read_version_verified", read)

    def sync():
        nonlocal syncs
        syncs += 1
        if syncs == 2:
            # Publication has committed. A replacement fence makes the original
            # facade's next synchronization authority check fail, not its upload.
            assert all(row.lifecycle_status == "finalized" for row in metadata(env, payloads))
            _replace_worker(env)
        source.check_authority()

    source.sync_events = sync
    with pytest.raises(LeaseLostError):
        if batch:
            source.store_payloads_immutable(payloads)
        else:
            identifier, payload = payloads[0]
            source.store_payload_immutable(payload, artifact_id=identifier)
    assert syncs == 2
    assert source_counts(env) == before + len(payloads)
    assert read.call_count == len(payloads)
    assert not source._verified_payloads and source._verified_bytes == 0
    for identifier, _ in payloads:
        with pytest.raises(LeaseLostError):
            source.read_payload_bytes(identifier)
    assert read.call_count == len(payloads)  # Revoked reads dispatch no new object I/O.


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("callback", ["presync", "authority", "postsync"])
def test_callback_mutation_cannot_change_frozen_publication_payload(
    publication, monkeypatch, batch, callback,
):
    env, source = publication, facade(publication)
    source.reuse_verified_payloads = True
    payloads = writes(env, 2 if batch else 1)
    originals = tuple(payload.model_copy(deep=True) for _, payload in payloads)
    check, syncs, mutated = source.check_authority, 0, False
    read = Mock(wraps=env.objects.read_version_verified)
    monkeypatch.setattr(env.objects, "read_version_verified", read)

    def mutate():
        nonlocal mutated
        # Deliberately bypass caller Pydantic freezing, as an arbitrary callback
        # can do. The worker must own a separate validated snapshot by this point.
        for _, payload in payloads:
            object.__setattr__(payload, "payload", b"callback-controlled bytes")
            object.__setattr__(payload, "file_name", "callback-controlled.txt")
        mutated = True

    def sync():
        nonlocal syncs
        syncs += 1
        if (callback == "presync" and syncs == 1) or (callback == "postsync" and syncs == 2):
            mutate()

    def authority():
        if callback == "authority" and not mutated:
            mutate()
        check()

    source.sync_events, source.check_authority = sync, authority
    if batch:
        stored = source.store_payloads_immutable(payloads)
    else:
        identifier, payload = payloads[0]
        stored = (source.store_payload_immutable(payload, artifact_id=identifier),)
    assert mutated and syncs == 2
    assert read.call_count == len(payloads)
    records = metadata(env, payloads)
    for row, item, original, (_, caller) in zip(records, stored, originals, payloads, strict=True):
        assert caller.payload != original.payload and caller.file_name != original.file_name
        assert row.lifecycle_status == "finalized"
        assert row.reservation.file_name == original.file_name
        assert source._stored(row) == item
        cached_record, body = source._verified_payloads[item.artifact_id]
        assert cached_record == row and body == original.payload
        assert source.read_payload_bytes(item.artifact_id) == original.payload
        receipt = row.object_receipt
        assert env.objects.read_version_verified(
            receipt.expectation, receipt.object_version,
        ) == original.payload
    assert source._verified_bytes == sum(len(payload.payload) for payload in originals)
    assert read.call_count == 2 * len(payloads)  # Cache reads add zero; independent originals do.


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("conflict", ["digest", "receipt_identity"])
def test_native_publication_ack_conflict_rejects_before_cache_seed(
    publication, monkeypatch, batch, conflict,
):
    env, source = publication, facade(publication)
    source.reuse_verified_payloads = True
    payloads = writes(env, 2 if batch else 1)
    before, acknowledgements, syncs = source_counts(env), [], 0
    finalize = publication_module.finalize_batch
    read = Mock(wraps=env.objects.read_version_verified)
    monkeypatch.setattr(env.objects, "read_version_verified", read)

    def capture(*args, **kwargs):
        result = finalize(*args, **kwargs)
        acknowledgements.extend(result)
        return result

    def sync():
        nonlocal syncs
        syncs += 1
        if syncs != 2:
            return
        # Capture only the real native result, retaining all publisher methods
        # and exact commit checks. Corrupt its in-memory ACK after that commit.
        row = acknowledgements[0]
        assert metadata(env, payloads)[0] == row
        if conflict == "digest":
            object.__setattr__(row.reservation, "sha256", "0" * 64)
        else:
            object.__setattr__(row.object_receipt.expectation, "artifact_id", uuid4())

    monkeypatch.setattr(publication_module, "finalize_batch", capture)
    source.sync_events = sync
    with pytest.raises(ValueError, match="acknowledgement conflicts with frozen bytes"):
        if batch:
            source.store_payloads_immutable(payloads)
        else:
            identifier, payload = payloads[0]
            source.store_payload_immutable(payload, artifact_id=identifier)
    assert syncs == 2 and len(acknowledgements) == len(payloads)
    assert source_counts(env) == before + len(payloads)
    assert not source._verified_payloads and source._verified_bytes == 0
    assert read.call_count == len(payloads)
    # ACK corruption never mutates the committed original or its physical bytes.
    for row, (identifier, payload) in zip(metadata(env, payloads), payloads, strict=True):
        assert row.lifecycle_status == "finalized" and row.artifact_id == identifier
        assert source.read_payload_bytes(identifier) == payload.payload
    assert read.call_count == 2 * len(payloads)
