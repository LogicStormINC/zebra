"""Certificate publication regressions in the existing disposable PostgreSQL schema."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID

import psycopg
import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import (
    CoverageRefusalReason,
    CoverageRefusedError,
    coverage_digest,
)
from agent_core.domain.coverage_execution import (
    CoverageExecutionBudget,
    CoverageObservation,
    CoverageQuote,
)
from agent_core.domain.coverage_persistence import coverage_manifest_bytes, coverage_result_bytes
from agent_core.domain.coverage_report import CoverageReport
from agent_core.domain.coverage_validation import AcceptedCoverageUnit, result_set_digest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId
from agent_storage import PostgresEventStore
from agent_storage.postgres import coverage_artifacts
from agent_storage.postgres.coverage import PostgresCoverageStore

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import (  # noqa: F401
    batch,
    bind,
    dsn,
    source_counts,
)
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401


def _artifact(env, body, kind):
    return env.artifacts.store_payload(ArtifactPayloadWrite(
        session_id=env.session.session_id, kind=kind, mime_type="application/json",
        payload=body, created_at=datetime.now(UTC),
    ))


@pytest.fixture
def publication(postgres_env):  # noqa: F811
    return _prepare_publication(postgres_env)


def _prepare_publication(env):
    bind(env)
    request = batch(env)
    observations = tuple(
        CoverageObservation(
            key=result.key, outcome="finding" if index % 2 == 0 else "clear",
            summary="Found a risk" if index % 2 == 0 else "No risk found",
            quotes=(CoverageQuote(part_id="body-0", start=0, end=3, text="abc"),)
            if index % 2 == 0 else (),
        )
        for index, result in enumerate(request.results)
    )
    accepted = tuple(AcceptedCoverageUnit(
        key=item.key, result_digest=item.digest, outcome=item.outcome,
    ) for item in observations)
    body = coverage_result_bytes(accepted)
    artifact = _artifact(env, body, "coverage-results")
    env.request = request.model_copy(update={
        "results": accepted, "result_artifact_ref": artifact.uri,
        "result_artifact_digest": sha256(body).hexdigest(),
    })
    env.report = CoverageReport(
        binding_digest=coverage_digest(env.binding.model_dump(mode="json")),
        result_set_digest=result_set_digest(accepted), observations=observations,
    )
    env.report_artifact = _artifact(env, env.report.canonical_bytes, "coverage-report")
    return env


def _certify(env, *, artifact=None, check_authority=lambda: None):
    artifact = env.report_artifact if artifact is None else artifact
    return env.store.certify(
        env.binding.namespace, env.binding.run_id,
        report_ref=artifact.uri, report_digest=artifact.sha256,
        fence=env.fence, check_authority=check_authority,
    )


def _read(env, *, now=None, check_authority=lambda: None):
    return env.store.certificate(
        env.binding.namespace, env.binding.run_id,
        now=datetime.now(UTC) if now is None else now, check_authority=check_authority,
    )


def test_certify_rejects_incomplete_accepted_units(publication):
    env = publication
    partial = batch(env, keys=(env.request.results[0].key,), key="partial")
    env.store.commit(partial, fence=env.fence)
    before = source_counts(env)
    with pytest.raises(ValueError, match="coverage is incomplete"):
        _certify(env)
    assert source_counts(env) == before
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (4, 1)
    assert _read(env) is None


def test_exact_report_certifies_once_and_retry_survives_store_restart(publication):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    before = source_counts(env)
    certificate = _certify(env)
    assert source_counts(env) == before + 1
    assert certificate.processed_units == len(env.request.results)
    assert certificate.result_set_digest == env.report.result_set_digest
    assert certificate.report_digest == env.report_artifact.sha256
    event = PostgresEventStore(env.dsn, deployment_namespace=NAMESPACE).list_for_session(
        env.session.session_id,
    )[-1]
    assert event.event_type == EventType.COVERAGE_REPORT_CERTIFIED
    assert certificate.event_watermark == event.sequence
    assert event.payload["report_ref"] == env.report_artifact.uri
    env.store = PostgresCoverageStore(
        env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts,
    )
    assert _certify(env) == certificate
    assert source_counts(env) == before + 1
    assert _read(env) == (certificate, env.report_artifact.uri)


def test_certified_run_rebuild_preserves_certificate_and_commit_retry(publication):
    env = publication
    receipt = env.store.commit(env.request, fence=env.fence)
    certificate = _certify(env)
    before = source_counts(env)
    env.store = PostgresCoverageStore(
        env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts,
    )
    assert env.store.rebuild(env.binding.namespace, env.binding.run_id) == (
        certificate.event_watermark
    )
    assert _read(env) == (certificate, env.report_artifact.uri)
    assert _certify(env) == certificate
    assert env.store.commit(env.request, fence=env.fence) == receipt
    assert source_counts(env) == before
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (4, 4)
    assert env.store.missing_units(env.binding.namespace, env.binding.run_id) == ()


def test_certified_run_rejects_new_commit_and_further_attempt(publication):
    env = publication
    receipt = env.store.commit(env.request, fence=env.fence)
    certificate = _certify(env)
    before = source_counts(env)
    assert env.store.commit(env.request, fence=env.fence) == receipt
    with pytest.raises(ValueError, match="certified"):
        env.store.commit(
            env.request.model_copy(update={"commit_key": "after-certification"}), fence=env.fence,
        )
    with pytest.raises(ValueError, match="certified"):
        env.store.reserve_attempt(
            env.binding, env.request.results[0].key, input_bytes=3,
            budget=CoverageExecutionBudget(max_attempts=10, max_input_bytes=100), fence=env.fence,
        )
    assert source_counts(env) == before
    assert _read(env) == (certificate, env.report_artifact.uri)


@pytest.mark.parametrize("change", ["observation", "omitted", "binding", "result_set"])
def test_changed_report_is_denied_without_appending_event(publication, change):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    certificate = _certify(env)
    changes = {
        "observation": {"observations": (
            env.report.observations[0].model_copy(update={"summary": "Changed conclusion"}),
            *env.report.observations[1:],
        )},
        "omitted": {"observations": env.report.observations[:-1]},
        "binding": {"binding_digest": "f" * 64},
        "result_set": {"result_set_digest": "e" * 64},
    }
    changed = env.report.model_copy(update=changes[change])
    artifact = _artifact(env, changed.canonical_bytes, "coverage-report")
    before = source_counts(env)
    with pytest.raises(ValueError, match="report"):
        _certify(env, artifact=artifact)
    assert source_counts(env) == before
    assert _read(env) == (certificate, env.report_artifact.uri)


def test_retry_with_same_report_bytes_but_changed_ref_is_denied(publication):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    certificate = _certify(env)
    replacement = _artifact(env, env.report.canonical_bytes, "coverage-report")
    assert replacement.sha256 == env.report_artifact.sha256
    assert replacement.uri != env.report_artifact.uri
    before = source_counts(env)
    with pytest.raises(ValueError, match="publication conflicts"):
        _certify(env, artifact=replacement)
    assert source_counts(env) == before
    assert _read(env) == (certificate, env.report_artifact.uri)


def test_expired_certificate_read_is_denied(publication):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    certificate = _certify(env)
    before = source_counts(env)
    with pytest.raises(ValueError, match="expired"):
        _read(env, now=certificate.expires_at)
    assert source_counts(env) == before


@pytest.mark.parametrize("revoke_on_call", [1, 2])
def test_revoked_authority_denies_certificate_read(publication, revoke_on_call):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    _certify(env)
    before = source_counts(env)
    calls = 0

    def check_authority():
        nonlocal calls
        calls += 1
        if calls == revoke_on_call:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        _read(env, check_authority=check_authority)
    assert calls == revoke_on_call
    assert source_counts(env) == before


@pytest.mark.parametrize("already_certified", [False, True])
def test_cancelled_run_denies_publication_and_certificate_read(publication, already_certified):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    if already_certified:
        _certify(env)
    env.store.cancel(env.binding.namespace, env.binding.run_id, fence=env.fence)
    before = source_counts(env)
    with pytest.raises(ValueError, match="cancelled"):
        _certify(env)
    with pytest.raises(ValueError, match="cancelled"):
        _read(env)
    assert source_counts(env) == before


def test_other_namespace_cannot_read_accepted_units_or_certificate(publication):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    certificate = _certify(env)
    before = source_counts(env)
    assert env.store.accepted_page(env.binding.namespace, env.binding.run_id)
    assert env.store.accepted_page("tenant-b", env.binding.run_id) == ()
    with pytest.raises(ValueError, match="not found in this namespace"):
        env.store.certificate(
            "tenant-b", env.binding.run_id, now=datetime.now(UTC), check_authority=lambda: None,
        )
    with pytest.raises(ValueError, match="not found in this namespace"):
        env.store.certify(
            "tenant-b", env.binding.run_id, report_ref=env.report_artifact.uri,
            report_digest=env.report_artifact.sha256, fence=env.fence,
            check_authority=lambda: None,
        )
    assert source_counts(env) == before
    assert _read(env) == (certificate, env.report_artifact.uri)


def _damage_artifact(env, ref, damage):
    artifact_id = ArtifactId(UUID(ref.removeprefix("artifact://")))
    metadata = env.artifacts.get_payload(artifact_id)
    body = env.artifacts.read_payload_bytes(artifact_id)
    if damage == "prune":
        env.artifacts.prune_payload(artifact_id)
        error = "coverage Artifact is unavailable"
    else:
        location = urlsplit(metadata.access_uri)
        assert location.scheme == "file"
        # Corrupt actual persisted bytes, keeping length and immutable metadata intact.
        Path(unquote(location.path)).write_bytes(b"!" + body[1:])
        assert env.artifacts.get_payload(artifact_id) == metadata
        error = "artifact payload bytes do not match immutable metadata"
    return error


@pytest.mark.parametrize("damage", ["prune", "corrupt"])
@pytest.mark.parametrize("already_certified", [False, True])
def test_batch_artifact_damage_refuses_certification_or_certificate_read(
    publication, damage, already_certified,
):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    if already_certified:
        certificate = _certify(env)
        assert _read(env) == (certificate, env.report_artifact.uri)
    before = source_counts(env)
    error = _damage_artifact(env, env.request.result_artifact_ref, damage)
    env.store = PostgresCoverageStore(
        env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts,
    )
    with pytest.raises(ValueError, match=error):
        _certify(env)
    if already_certified:
        with pytest.raises(ValueError, match=error):
            _read(env)
    else:
        assert _read(env) is None
    assert source_counts(env) == before
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (4, 4)
    assert env.artifacts.read_payload_bytes(env.report_artifact.artifact_id) == (
        env.report.canonical_bytes
    )


@pytest.mark.parametrize("damage", ["prune", "corrupt"])
def test_manifest_artifact_damage_after_certification_denies_certificate_read(publication, damage):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    certificate = _certify(env)
    assert _read(env) == (certificate, env.report_artifact.uri)
    before = source_counts(env)
    error = _damage_artifact(env, env.binding.snapshot.manifest_artifact_ref, damage)
    env.store = PostgresCoverageStore(
        env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts,
    )
    with pytest.raises(ValueError, match=error):
        _read(env)
    assert source_counts(env) == before
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (4, 4)
    assert env.artifacts.read_payload_bytes(env.report_artifact.artifact_id) == (
        env.report.canonical_bytes
    )
    batch_id = ArtifactId(UUID(env.request.result_artifact_ref.removeprefix("artifact://")))
    assert env.artifacts.read_payload_bytes(batch_id) == coverage_result_bytes(env.request.results)


def test_manifest_retention_expiry_denies_certificate_read(postgres_env, monkeypatch):  # noqa: F811
    env = postgres_env
    now = datetime.now(UTC)
    retained_until = now + timedelta(seconds=30)
    body = coverage_manifest_bytes(env.items)
    manifest = env.artifacts.store_payload(ArtifactPayloadWrite(
        session_id=env.session.session_id, kind="coverage-manifest", mime_type="application/json",
        payload=body, created_at=now, retained_until=retained_until,
    ))
    env.binding = env.binding.model_copy(update={"snapshot": env.binding.snapshot.model_copy(
        update={"manifest_artifact_ref": manifest.uri},
    )})
    _prepare_publication(env)
    env.store.commit(env.request, fence=env.fence)
    certificate = _certify(env)
    assert _read(env) == (certificate, env.report_artifact.uri)
    before = source_counts(env)
    advanced = retained_until + timedelta(seconds=1)
    assert advanced < certificate.expires_at

    class Clock:
        @staticmethod
        def now(tz):
            return advanced.astimezone(tz)

    with monkeypatch.context() as patch:
        patch.setattr(coverage_artifacts, "datetime", Clock)
        with pytest.raises(ValueError, match="coverage Artifact is unavailable"):
            _read(env)
    assert source_counts(env) == before
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (4, 4)
    assert env.artifacts.get_payload(manifest.artifact_id) == manifest
    assert env.artifacts.read_payload_bytes(manifest.artifact_id) == body
    assert _read(env) == (certificate, env.report_artifact.uri)


@pytest.mark.parametrize("evidence", ["manifest", "report", "batch"])
@pytest.mark.parametrize("reading", [False, True])
def test_final_authority_callback_prunes_evidence_failclosed(publication, evidence, reading):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    if reading:
        _certify(env)
    before = source_counts(env)
    refs = {"manifest": env.binding.snapshot.manifest_artifact_ref,
            "report": env.report_artifact.uri, "batch": env.request.result_artifact_ref}
    calls = 0

    def check_authority():
        nonlocal calls
        calls += 1
        if calls == 2:
            _damage_artifact(env, refs[evidence], "prune")

    with pytest.raises(ValueError, match="coverage Artifact"):
        (_read if reading else _certify)(env, check_authority=check_authority)
    assert calls == 2
    assert source_counts(env) == before


@pytest.mark.parametrize("reading", [False, True])
def test_final_authority_callback_cancels_publication(publication, reading):
    env = publication
    env.store.commit(env.request, fence=env.fence)
    if reading:
        _certify(env)
    before = source_counts(env)
    calls = 0

    def check_authority():
        nonlocal calls
        calls += 1
        if calls == 2:
            env.store.cancel(env.binding.namespace, env.binding.run_id, fence=env.fence)

    with pytest.raises(ValueError, match="cancelled"):
        (_read if reading else _certify)(env, check_authority=check_authority)
    assert calls == 2
    assert source_counts(env) == before + 1


@pytest.mark.parametrize("evidence", ["manifest", "report", "batch"])
def test_prune_after_certified_event_rolls_back_publication(publication, monkeypatch, evidence):
    from agent_storage.postgres import coverage_publication

    env = publication
    env.store.commit(env.request, fence=env.fence)
    before = source_counts(env)
    refs = {"manifest": env.binding.snapshot.manifest_artifact_ref,
            "report": env.report_artifact.uri, "batch": env.request.result_artifact_ref}
    original = coverage_publication.project_watermark

    def prune_after_projection(*args, **kwargs):
        original(*args, **kwargs)
        _damage_artifact(env, refs[evidence], "prune")

    monkeypatch.setattr(coverage_publication, "project_watermark", prune_after_projection)
    with pytest.raises(ValueError, match="coverage Artifact"):
        _certify(env)
    assert source_counts(env) == before
    assert _read(env) is None


@pytest.fixture
def cloud_publication(publication):
    from agent_storage import PostgresCloudArtifactPayloadStore, S3ArtifactObjectStore

    from tests.agent_storage.test_coverage_artifact_publication import _publisher
    from tests.agent_storage.test_s3_artifact_objects import _FakeS3Client
    from tests.worker.test_coverage_artifacts import facade

    env = publication
    env.events = PostgresEventStore(env.dsn, deployment_namespace=NAMESPACE)
    env.metadata = PostgresCloudArtifactPayloadStore(env.dsn, deployment_namespace=NAMESPACE)
    env.objects = S3ArtifactObjectStore(_FakeS3Client(), bucket="coverage-lock-tests")
    env.publisher = _publisher(env)
    cloud = facade(env)
    env.evidence_refs = (env.binding.snapshot.manifest_artifact_ref,
                         env.report_artifact.uri, env.request.result_artifact_ref)
    for ref in env.evidence_refs:
        artifact_id = ArtifactId(UUID(ref.removeprefix("artifact://")))
        stored = env.artifacts.get_payload(artifact_id)
        cloud.store_payload_immutable(ArtifactPayloadWrite(
            session_id=env.session.session_id, kind=stored.kind, mime_type=stored.mime_type,
            payload=env.artifacts.read_payload_bytes(artifact_id), created_at=stored.created_at,
        ), artifact_id=artifact_id)
    env.artifacts = cloud
    env.store = PostgresCoverageStore(env.dsn, deployment_namespace=NAMESPACE, artifacts=cloud)
    env.store.commit(env.request, fence=env.fence)
    return env


@pytest.mark.parametrize("reading", [False, True])
def test_cloud_publication_holds_all_evidence_locks_until_return(
    cloud_publication, monkeypatch, reading,
):
    env = cloud_publication
    if reading:
        _certify(env)
    original = env.store._check_publication_lifecycle
    checked = 0

    def verify_locks(*args):
        nonlocal checked
        original(*args)
        checked += 1
        for ref in env.evidence_refs:
            with psycopg.connect(env.dsn) as other:
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    other.execute(
                        """SELECT 1 FROM artifact_payload_metadata
                           WHERE deployment_namespace=%s AND artifact_id=%s FOR UPDATE NOWAIT""",
                        (NAMESPACE, UUID(ref.removeprefix("artifact://"))),
                    )

    monkeypatch.setattr(env.store, "_check_publication_lifecycle", verify_locks)
    (_read if reading else _certify)(env)
    assert checked == (1 if reading else 2)
    with psycopg.connect(env.dsn) as other:
        assert len(other.execute(
            "SELECT 1 FROM artifact_payload_metadata FOR UPDATE NOWAIT"
        ).fetchall()) == 3


@pytest.mark.parametrize("evidence", ["manifest", "report", "batch"])
@pytest.mark.parametrize("reading", [False, True])
def test_cloud_final_callback_begin_prune_refuses_publication(cloud_publication, evidence, reading):
    from agent_core.domain.cloud_artifact_requests import ArtifactBeginPruneRequest

    from tests.agent_storage.test_coverage_artifact_publication import _authority

    env = cloud_publication
    if reading:
        _certify(env)
    before = source_counts(env)
    artifact_id = ArtifactId(UUID(env.evidence_refs[("manifest", "report", "batch").index(
        evidence,
    )].removeprefix("artifact://")))
    calls = 0

    def check_authority():
        nonlocal calls
        calls += 1
        if calls == 2:
            env.metadata.begin_prune_for_worker(ArtifactBeginPruneRequest(
                artifact_id=artifact_id, session_id=env.session.session_id,
                expected_lifecycle_revision=2, idempotency_key=f"prune:{artifact_id}",
                requested_at=datetime.now(UTC),
            ), authority=_authority(env))

    with pytest.raises(ValueError, match="coverage Artifact"):
        (_read if reading else _certify)(env, check_authority=check_authority)
    assert calls == 2
    assert source_counts(env) == before


def test_completed_session_certificate_remains_readable(cloud_publication):
    env = cloud_publication
    certificate = _certify(env)
    previous = env.events.list_for_session(env.session.session_id)[-1]
    env.events.append(SessionEvent.create(
        session_id=env.session.session_id, sequence=previous.sequence + 1,
        event_type=EventType.SESSION_COMPLETED, actor=EventActor.SYSTEM,
    ))
    env.leases.release(env.session.session_id, fence=env.fence)
    before = source_counts(env)
    assert _read(env) == (certificate, env.report_artifact.uri)
    assert source_counts(env) == before


@pytest.mark.parametrize("stop", ["stop", "cancel", "session_failed", "session_cancelled"])
def test_final_callback_stops_session_refuses_certificate_read(cloud_publication, stop):
    from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind

    env = cloud_publication
    _certify(env)
    before = source_counts(env)
    calls = 0

    def check_authority():
        nonlocal calls
        calls += 1
        if calls != 2:
            return
        previous = env.events.list_for_session(env.session.session_id)[-1]
        if stop in {"stop", "cancel"}:
            command = SessionCommand(
                session_id=env.session.session_id, kind=SessionCommandKind(stop),
                expected_revision=previous.sequence, idempotency_key=f"final-{stop}",
            )
            payload = command.event_payload()
            assert payload["kind"] == stop  # SQL reads the actual accepted command shape.
            event_type = EventType.SESSION_COMMAND_ACCEPTED
        else:
            payload, event_type = {}, EventType(stop)
        env.events.append(SessionEvent.create(
            session_id=env.session.session_id, sequence=previous.sequence + 1,
            event_type=event_type, actor=EventActor.USER, payload=payload,
        ))

    with pytest.raises(ValueError, match="terminal or has accepted STOP/cancel"):
        _read(env, check_authority=check_authority)
    assert calls == 2
    assert source_counts(env) == before + 1


@pytest.mark.parametrize("retry", [False, True])
def test_cloud_authority_revoked_during_source_validation_refuses_certification(
    cloud_publication, monkeypatch, retry,
):
    env = cloud_publication
    certificate = _certify(env) if retry else None
    before = source_counts(env)
    original = env.store._verify_result_sources
    revoked = False
    checks = 0

    def revoke_after_validation(*args, **kwargs):
        nonlocal revoked
        result = original(*args, **kwargs)
        revoked = True
        return result

    def check_authority():
        nonlocal checks
        checks += 1
        if revoked:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    with monkeypatch.context() as patch:
        patch.setattr(env.store, "_verify_result_sources", revoke_after_validation)
        with pytest.raises(CoverageRefusedError, match="authority_invalid"):
            _certify(env, check_authority=check_authority)
    assert revoked and checks == 3
    assert source_counts(env) == before
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (4, 4)
    assert _read(env) == ((certificate, env.report_artifact.uri) if retry else None)


@pytest.mark.parametrize("retry", [False, True])
def test_cloud_lease_expiry_during_final_lifecycle_scan_rolls_back_certification(
    cloud_publication, monkeypatch, retry,
):
    from agent_core.domain.leases import LeaseLostError

    env = cloud_publication
    certificate = _certify(env) if retry else None
    before = source_counts(env)
    original = env.store._check_publication_lifecycle
    scans = 0

    def slow_final_scan(connection, *args):
        nonlocal scans
        original(connection, *args)
        scans += 1
        if scans == 2:
            connection.execute("SELECT pg_sleep(1.2)")

    env.leases.heartbeat(
        env.session.session_id, fence=env.fence, ttl=timedelta(seconds=1), checkpoint=0,
    )
    with monkeypatch.context() as patch:
        patch.setattr(env.store, "_check_publication_lifecycle", slow_final_scan)
        with pytest.raises(LeaseLostError):
            _certify(env)
    assert scans == 2
    assert source_counts(env) == before
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (4, 4)
    assert _read(env) == ((certificate, env.report_artifact.uri) if retry else None)
