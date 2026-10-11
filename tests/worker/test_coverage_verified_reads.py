"""Coalesced object reads keep both fresh authority boundaries, including reuse."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_storage.postgres.coverage_artifacts import read_artifact
from agent_storage.postgres.coverage_model_checkpoint import _CheckpointBodies
from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts


def fixture():
    artifact, session = ArtifactId(uuid4()), SessionId(uuid4())
    reservation = SimpleNamespace(
        kind=MODEL_CHECKPOINT_KIND,
        mime_type="application/json",
        size_bytes=2,
        sha256=sha256(b"{}").hexdigest(),
        retained_until=datetime.now(UTC) + timedelta(hours=1),
        created_at=datetime.now(UTC),
    )
    record = SimpleNamespace(
        artifact_id=artifact,
        session_id=session,
        reservation=reservation,
        uri=f"artifact://{artifact}",
        lifecycle_status=CloudArtifactPayloadLifecycleStatus.FINALIZED,
        object_receipt=SimpleNamespace(expectation="expected", object_version="v1"),
    )
    metadata, objects, authority = Mock(), Mock(), Mock()
    metadata.get_metadata.return_value = record
    objects.read_version_verified.return_value = b"{}"
    reader = CloudCoverageArtifacts(
        binding=SimpleNamespace(session_id=session),
        deployment_namespace="fixture",
        metadata=metadata,
        objects=objects,
        publisher=Mock(),
        authority=Mock(),
        check_authority=authority,
        sync_events=Mock(),
    )
    return reader, record, authority


def test_read_has_exactly_two_authority_checks_not_four():
    reader, record, authority = fixture()
    assert read_artifact(reader, record.uri, record.reservation.sha256, record.session_id) == b"{}"
    assert authority.call_count == 2
    assert reader.metadata.get_metadata.call_count == 2
    assert reader.objects.read_version_verified.call_count == 1


def test_incremental_reuse_keeps_current_metadata_and_independent_final_reads():
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    reader, record, authority = fixture()
    reader.reuse_verified_payloads = True
    for _ in range(3):
        assert read_artifact(
            reader, record.uri, record.reservation.sha256, record.session_id
        ) == b"{}"
    assert authority.call_count == 6
    assert reader.metadata.get_metadata.call_count == 6
    assert reader.objects.read_version_verified.call_count == 1
    assert reader._verified_bytes == 2
    # A certification phase never imports this incremental cache.
    with reader._locked_proof_scope(
        object(), reader.deployment, reader.binding, derive=derive_semantic_observation,
        final_certification=True,
    ) as fresh:
        assert not fresh.reuse_verified_payloads and not fresh._verified_payloads


def test_incremental_reuse_refuses_revocation_and_changed_object_version():
    reader, record, authority = fixture()
    reader.reuse_verified_payloads = True
    read_artifact(reader, record.uri, record.reservation.sha256, record.session_id)
    record.object_receipt.object_version = "v2"
    read_artifact(reader, record.uri, record.reservation.sha256, record.session_id)
    assert reader.objects.read_version_verified.call_count == 2
    authority.side_effect = ValueError("revoked")
    with pytest.raises(ValueError, match="revoked"):
        read_artifact(reader, record.uri, record.reservation.sha256, record.session_id)


def test_incremental_cache_has_hard_entry_and_byte_limits():
    reader, record, _ = fixture()
    reader.reuse_verified_payloads = True
    for _ in range(258):
        record.artifact_id = ArtifactId(uuid4())
        reader.read_payload_bytes_bounded(record.artifact_id, max_bytes=2)
    assert len(reader._verified_payloads) == 256
    assert reader._verified_bytes == 512
    body = b"x" * (17 * 1024 * 1024)
    record.reservation.size_bytes = len(body)
    record.reservation.sha256 = sha256(body).hexdigest()
    reader.objects.read_version_verified.return_value = body
    for _ in range(2):
        record.artifact_id = ArtifactId(uuid4())
        reader.read_payload_bytes_bounded(record.artifact_id, max_bytes=len(body))
    assert len(reader._verified_payloads) == 1
    assert reader._verified_bytes == len(body)
    assert reader._verified_bytes == sum(
        len(entry[1]) for entry in reader._verified_payloads.values()
    )


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_authority_revocation_cannot_be_coalesced_away(boundary):
    reader, record, authority = fixture()
    authority.side_effect = (
        [ValueError("revoked")] if boundary == "before" else [None, ValueError("revoked")]
    )
    with pytest.raises(ValueError, match="revoked"):
        read_artifact(reader, record.uri, record.reservation.sha256, record.session_id)
    assert reader.objects.read_version_verified.call_count == (boundary == "after")


@pytest.mark.parametrize("change", ["session", "digest", "identity", "expired"])
def test_mismatched_identity_refuses_before_object_io(change):
    reader, record, _ = fixture()
    session, digest = record.session_id, record.reservation.sha256
    if change == "session":
        session = SessionId(uuid4())
    elif change == "digest":
        digest = "f" * 64
    elif change == "identity":
        reader.metadata.get_metadata.return_value = SimpleNamespace(
            **(vars(record) | {"artifact_id": ArtifactId(uuid4())})
        )
    else:
        record.reservation.retained_until = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(ValueError):
        read_artifact(reader, record.uri, digest, session)
    reader.objects.read_version_verified.assert_not_called()


def test_lifecycle_change_after_physical_read_refuses():
    reader, record, _ = fixture()
    reader.metadata.get_metadata.side_effect = [record, None]
    with pytest.raises(ValueError, match="changed"):
        read_artifact(reader, record.uri, record.reservation.sha256, record.session_id)


def test_object_version_change_after_read_refuses_even_when_digest_matches():
    reader, record, _ = fixture()
    changed = SimpleNamespace(
        **(
            vars(record)
            | {"object_receipt": SimpleNamespace(expectation="expected", object_version="v2")}
        )
    )
    reader.metadata.get_metadata.side_effect = [record, changed]
    with pytest.raises(ValueError, match="changed"):
        read_artifact(reader, record.uri, record.reservation.sha256, record.session_id)


def test_corrupt_bytes_are_still_rejected():
    reader, record, _ = fixture()
    reader.objects.read_version_verified.return_value = b"[]"
    with pytest.raises(ValueError, match="corrupt"):
        read_artifact(reader, record.uri, record.reservation.sha256, record.session_id)


def test_corrupt_checkpoint_is_never_cached():
    reader, record, _ = fixture()
    proof = _CheckpointBodies(reader)
    reader.objects.read_version_verified.return_value = b"[]"
    with pytest.raises(ValueError, match="corrupt"):
        read_artifact(proof, record.uri, record.reservation.sha256, record.session_id)
    assert not proof._bodies and proof._size == 0


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_cached_checkpoint_still_rejects_revocation(boundary):
    reader, record, authority = fixture()
    proof = _CheckpointBodies(reader)
    read_artifact(proof, record.uri, record.reservation.sha256, record.session_id)
    authority.side_effect = (
        [ValueError("revoked")] if boundary == "before" else [None, ValueError("revoked")]
    )
    with pytest.raises(ValueError, match="revoked"):
        read_artifact(proof, record.uri, record.reservation.sha256, record.session_id)
    assert reader.objects.read_version_verified.call_count == 1


def test_checkpoint_reuse_keeps_two_fresh_checks_and_new_proof_rereads():
    reader, record, authority = fixture()
    proof = _CheckpointBodies(reader)
    for _ in range(3):
        assert (
            read_artifact(proof, record.uri, record.reservation.sha256, record.session_id) == b"{}"
        )
    assert authority.call_count == 6
    assert reader.objects.read_version_verified.call_count == 1
    assert proof._size == 2
    read_artifact(
        _CheckpointBodies(reader), record.uri, record.reservation.sha256, record.session_id
    )
    assert reader.objects.read_version_verified.call_count == 2
    reader.metadata.get_metadata.return_value = None
    with pytest.raises(ValueError):
        read_artifact(proof, record.uri, record.reservation.sha256, record.session_id)


@pytest.mark.parametrize("kind", ["coverage-manifest", "coverage-results", "coverage-observation"])
def test_verified_non_checkpoint_proof_bodies_are_unique_per_phase(kind):
    reader, record, authority = fixture()
    record.reservation.kind = kind
    phase = _CheckpointBodies(reader)
    for _ in range(3):
        assert (
            read_artifact(phase, record.uri, record.reservation.sha256, record.session_id) == b"{}"
        )
    assert reader.objects.read_version_verified.call_count == 1
    assert authority.call_count == 6  # Public reader still has per-getter authority.
    assert phase._size == 2
    read_artifact(
        _CheckpointBodies(reader), record.uri, record.reservation.sha256, record.session_id
    )
    assert reader.objects.read_version_verified.call_count == 2


def test_checkpoint_cache_overflow_uses_io(monkeypatch):
    from agent_storage.postgres import coverage_artifacts

    reader, record, authority = fixture()
    proof = _CheckpointBodies(reader)
    proof._size = coverage_artifacts.MAX_COVERAGE_ARTIFACT_BYTES
    for _ in range(2):
        read_artifact(proof, record.uri, record.reservation.sha256, record.session_id)
    assert not proof._bodies
    assert reader.objects.read_version_verified.call_count == 2
    assert authority.call_count == 4


@pytest.mark.parametrize("mismatch", [None, "kind", "mime_type", "size_bytes", "retained_until"])
def test_checkpoint_pins_before_read_and_reuses_verified_metadata(monkeypatch, mismatch):
    from agent_storage.postgres import coverage_model_checkpoint as module

    reader, record, authority = fixture()
    locked = SimpleNamespace(**vars(record))
    locked.reservation = SimpleNamespace(**vars(record.reservation))
    if mismatch is not None:
        replacement = {
            "kind": "other", "mime_type": "text/plain", "size_bytes": 3,
            "retained_until": datetime.now(UTC) + timedelta(days=2),
        }[mismatch]
        setattr(locked.reservation, mismatch, replacement)
    pinned = []

    def pin(*args, **kwargs):
        pinned.append(True)
        return locked

    def check():
        assert pinned, "canonical lifecycle must be pinned before any reader access"

    authority.side_effect = check
    binding, receipt = reader.binding, object()
    checkpoint = SimpleNamespace(binding=binding, validate_receipt=Mock())
    monkeypatch.setattr(module, "checkpoint_source", pin)
    monkeypatch.setattr(module, "decode_model_checkpoint", lambda body: checkpoint)
    retention = Mock()
    monkeypatch.setattr(module, "check_checkpoint_retention", retention)

    def verify():
        return module.verify_model_checkpoint(
            object(), "fixture", binding, receipt, reader, reserved_sequence=1,
        )

    if mismatch is not None:
        with pytest.raises(ValueError, match="locked metadata"):
            verify()
        checkpoint.validate_receipt.assert_not_called()
    else:
        assert verify() == b"{}"
        checkpoint.validate_receipt.assert_called_once_with(receipt)
        retention.assert_called_once()
    assert authority.call_count == 2
    assert reader.metadata.get_metadata.call_count == 2
    assert reader.objects.read_version_verified.call_count == 1
