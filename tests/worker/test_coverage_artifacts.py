"""Worker coverage facade against isolated PostgreSQL and versioned fake S3."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.identifiers import ArtifactId
from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts
from zebra_agent_worker.coverage_recovery_preparation import RecoveryArtifactReads

from tests.agent_storage.test_coverage_artifact_publication import (
    _authority,
    _crash,
    publication,  # noqa: F401 - imported pytest fixture
)
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401


def facade(env, *, check=lambda: None):
    return CloudCoverageArtifacts(
        binding=env.binding,
        deployment_namespace=NAMESPACE,
        metadata=env.metadata,
        objects=env.objects,
        publisher=env.publisher,
        authority=lambda: _authority(env),
        check_authority=check,
        sync_events=lambda: None,
    )


def test_finalized_payload_is_bounded_and_survives_facade_restart(publication):  # noqa: F811
    env = publication
    first = facade(env)
    stored = first.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    assert stored.uri == f"artifact://{env.artifact_id}"
    fresh = facade(env)
    assert fresh.read_payload_bytes_bounded(
        env.artifact_id, max_bytes=len(env.payload.payload)
    ) == (env.payload.payload)
    with pytest.raises(ValueError, match="read bound"):
        fresh.read_payload_bytes_bounded(env.artifact_id, max_bytes=len(env.payload.payload) - 1)
    assert fresh.get_payload(env.artifact_id) == stored
    assert fresh.store_payload_immutable(env.payload, artifact_id=env.artifact_id) == stored


@pytest.mark.parametrize("stage", ["upload", "receipt"])
def test_staged_payload_not_readable_until_recovered(publication, monkeypatch, stage):  # noqa: F811
    env = publication
    _crash(env, monkeypatch, stage)
    current = facade(env)
    assert current.get_payload(env.artifact_id) is None
    assert current.inspect_payload(env.artifact_id) is None
    with pytest.raises(ValueError, match="unavailable"):
        current.read_payload_bytes(env.artifact_id)
    current.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    assert current.read_payload_bytes(env.artifact_id) == env.payload.payload


def test_revocation_during_object_read_discards_bytes(publication, monkeypatch):  # noqa: F811
    env = publication
    current = facade(env)
    current.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    revoked = False
    original = env.objects.read_version_verified

    def check():
        if revoked:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    def read(*args):
        nonlocal revoked
        data = original(*args)
        revoked = True
        return data

    current.check_authority = check
    monkeypatch.setattr(env.objects, "read_version_verified", read)
    with pytest.raises(CoverageRefusedError):
        current.read_payload_bytes(env.artifact_id)


@pytest.mark.parametrize("cached", [False, True])
def test_prepared_read_has_two_fresh_guards_and_refuses_post_read_revocation(
    publication, monkeypatch, cached  # noqa: F811
):
    env = publication
    current = facade(env)
    current.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    checks, physical_reads = 0, 0
    refuse = False
    original = env.objects.read_version_verified

    def check():
        nonlocal checks
        checks += 1
        if refuse and checks == 2:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    def read(*args):
        nonlocal physical_reads
        physical_reads += 1
        return original(*args)

    current.check_authority = check
    monkeypatch.setattr(env.objects, "read_version_verified", read)
    with env.metadata._database.connect() as connection:
        reads = RecoveryArtifactReads(current, connection, {})
        if cached:
            assert reads.read_payload_bytes(env.artifact_id) == env.payload.payload
            assert checks == 2 and physical_reads == 1
            checks = 0
        refuse = True
        with pytest.raises(CoverageRefusedError):
            reads.read_payload_bytes(env.artifact_id)
        assert checks == 2 and physical_reads == 1
        if not cached:
            assert not reads._bodies and not reads.originals


def test_unknown_identity_and_worker_pruning_are_refused(publication):  # noqa: F811
    current = facade(publication)
    unknown = ArtifactId(UUID(int=99))
    assert current.get_payload(unknown) is None
    with pytest.raises(ValueError, match="deterministic"):
        current.store_payload(publication.payload)
    with pytest.raises(ValueError, match="cannot prune"):
        current.prune_payload(unknown)
    with pytest.raises(ValueError, match="cannot sweep"):
        current.sweep_expired_payloads()


def test_expired_payload_is_not_reported_available_or_readable(publication, monkeypatch):  # noqa: F811
    env = publication
    expires = datetime.now(UTC) + timedelta(seconds=30)
    payload = env.payload.model_copy(update={"retained_until": expires})
    current = facade(env)
    current.store_payload_immutable(payload, artifact_id=env.artifact_id)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return expires

    monkeypatch.setattr("zebra_agent_worker.coverage_artifacts.datetime", Clock)
    assert current.get_payload(env.artifact_id) is None
    assert current.inspect_payload(env.artifact_id) is None
    with pytest.raises(ValueError, match="unavailable"):
        current.read_payload_bytes(env.artifact_id)
    with pytest.raises(ValueError, match="retention has expired"):
        current.store_payload_immutable(payload, artifact_id=env.artifact_id)
