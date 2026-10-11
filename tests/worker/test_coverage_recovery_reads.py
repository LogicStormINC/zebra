"""Preparation-local byte reuse never caches lifecycle or final authority."""

from dataclasses import dataclass, replace
from hashlib import sha256
from types import SimpleNamespace

import pytest
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from zebra_agent_worker import coverage_recovery_preparation as preparation
from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts


@dataclass(frozen=True)
class Record:
    version: str = "v1"
    reservation: object = None
    lifecycle_status: object = CloudArtifactPayloadLifecycleStatus.FINALIZED
    lifecycle_revision: int = 2
    object_receipt: object = "receipt"


def reader(monkeypatch):
    record = Record(
        reservation=SimpleNamespace(size_bytes=4, sha256=sha256(b"body").hexdigest()),
        object_receipt=SimpleNamespace(expectation="expected", object_version="v1"),
    )

    class Artifacts:
        deployment = "fixture"
        binding = SimpleNamespace(session_id="session")
        current = record
        reads = 0
        checks = 0
        def after_read(self):
            pass

        def _record(self, artifact):
            self.checks += 1
            return self.current

        _read_payload_bytes_for_record = CloudCoverageArtifacts._read_payload_bytes_for_record

        def read_version_verified(self, expectation, version):
            assert (expectation, version) == ("expected", "v1")
            self.reads += 1
            self.after_read()
            return b"body"

    artifacts = Artifacts()
    artifacts.objects = artifacts
    artifacts._verified_payload_owner = artifacts
    artifacts.reuse_verified_payloads = False  # Exercise only the preparation-local cache.
    monkeypatch.setattr(preparation, "lock_payload", lambda *_: artifacts.current)
    monkeypatch.setattr(preparation, "artifact_payload_from_row", lambda row: row)
    originals = {}
    return artifacts, preparation.RecoveryArtifactReads(artifacts, object(), originals), originals


def test_same_preparation_reads_once_but_checks_fresh_metadata_each_use(monkeypatch):
    artifacts, reads, originals = reader(monkeypatch)
    for _ in range(10):
        assert reads.read_payload_bytes_bounded("a", max_bytes=4) == b"body"
    assert artifacts.reads == 1 and artifacts.checks == 20
    assert len(originals) == 1 and reads._size == 4
    # Separate preparation must physically read again, not trust the prior digest.
    fresh = preparation.RecoveryArtifactReads(artifacts, object(), {})
    fresh.read_payload_bytes_bounded("a", max_bytes=4)
    assert artifacts.reads == 2


@pytest.mark.parametrize("max_bytes", [True, -1, 32 * 1024 * 1024 + 1, 3])
def test_cached_bytes_do_not_bypass_new_physical_bound(monkeypatch, max_bytes):
    artifacts, reads, _ = reader(monkeypatch)
    reads.read_payload_bytes_bounded("a", max_bytes=4)
    with pytest.raises(ValueError, match="bound"):
        reads.read_payload_bytes_bounded("a", max_bytes=max_bytes)
    assert artifacts.reads == 1


@pytest.mark.parametrize("change", ["version", "revision", "unavailable", "during_read"])
def test_fresh_version_lifecycle_or_concurrent_change_refuses(monkeypatch, change):
    artifacts, reads, _ = reader(monkeypatch)
    if change == "during_read":
        artifacts.after_read = lambda: setattr(
            artifacts, "current", replace(artifacts.current, version="v2")
        )
    else:
        reads.read_payload_bytes_bounded("a", max_bytes=4)
        artifacts.current = {
            "version": replace(artifacts.current, version="v2"),
            "revision": replace(artifacts.current, lifecycle_revision=3),
            "unavailable": None,
        }[change]
    with pytest.raises(ValueError, match="physical|original|changed while reading"):
        reads.read_payload_bytes_bounded("a", max_bytes=4)


def test_capacity_falls_back_to_io_without_increasing_cache_or_refusing(monkeypatch):
    artifacts, reads, originals = reader(monkeypatch)
    monkeypatch.setattr(preparation, "MAX_COVERAGE_ARTIFACT_BYTES", 4)
    for artifact in ("a", "b", "b", "a"):
        reads.read_payload_bytes_bounded(artifact, max_bytes=4)
    assert artifacts.reads == 3 and reads._size == 4 and set(reads._bodies) == {"a"}
    assert set(originals) == {"a", "b"}


def test_expired_fresh_record_cannot_use_snapshot_or_cached_body(monkeypatch):
    artifacts, reads, _ = reader(monkeypatch)
    reads.read_payload_bytes_bounded("a", max_bytes=4)
    pinned = artifacts.current
    monkeypatch.setattr(preparation, "lock_payload", lambda *_: pinned)
    artifacts.current = None  # Real _record returns None once retention expires.
    with pytest.raises(ValueError, match="physical"):
        reads.read_payload_bytes_bounded("a", max_bytes=4)
    assert artifacts.reads == 1


def test_original_digest_is_validated_before_byte_reuse(monkeypatch):
    artifacts, reads, originals = reader(monkeypatch)
    artifacts.current = replace(
        artifacts.current, reservation=SimpleNamespace(size_bytes=4, sha256="0" * 64)
    )
    with pytest.raises(ValueError, match="reservation"):
        reads.read_payload_bytes_bounded("a", max_bytes=4)
    assert not reads._bodies and not originals


def test_cache_hit_rechecks_metadata_after_reuse(monkeypatch):
    artifacts, reads, _ = reader(monkeypatch)
    reads.read_payload_bytes_bounded("a", max_bytes=4)
    original = artifacts._record

    def changed_after_first_check(artifact):
        if artifacts.checks == 3:
            artifacts.current = replace(artifacts.current, version="v2")
        return original(artifact)

    artifacts._record = changed_after_first_check
    with pytest.raises(ValueError, match="changed during"):
        reads.read_payload_bytes_bounded("a", max_bytes=4)
    assert artifacts.reads == 1
