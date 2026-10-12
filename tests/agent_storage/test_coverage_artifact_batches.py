"""Native batch publication laws; object transport is explicitly controlled fake S3."""
# ruff: noqa: F811

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier, Event, local
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadLifecycleStatus,
)
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres import coverage_artifact_publication as module
from agent_storage.postgres.work_unit import borrow_work_unit

from tests.agent_storage.test_coverage_artifact_publication import (
    _authority,
    _replace_worker,
)
from tests.agent_storage.test_coverage_artifact_publication import publication as publication
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import dsn, source_counts  # noqa: F401
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401


def writes(env, count=3):
    return tuple((ArtifactId(uuid4()), env.payload.model_copy(update={
        "payload": f"object-{number}".encode(),
    })) for number in range(count))


def publish(env, payloads, check=lambda: None):
    return env.publisher.publish_batch(
        env.binding, payloads, authority=_authority(env), check_authority=check,
    )


def metadata(env, payloads):
    return tuple(env.metadata.get_metadata(ArtifactMetadataQuery(
        deployment_namespace=NAMESPACE, session_id=env.session.session_id, artifact_id=identifier,
    )) for identifier, _ in payloads)


def test_batch_order_retry_and_mixed_finalized_new_evidence(publication):
    env, payloads = publication, writes(publication)
    before = source_counts(env)
    revision = _authority(env).expected_stream_revision
    result = publish(env, payloads)
    assert tuple(row.artifact_id for row in result) == tuple(key for key, _ in payloads)
    assert all(row.lifecycle_status == "finalized" and row.lifecycle_revision == 2
               for row in result)
    assert len({row.event_binding.event_id for row in result}) == 3
    assert [row.event_binding.sequence for row in result] == list(range(revision + 1, revision + 4))
    assert publish(env, payloads) == result
    added = writes(env, 2)
    mixed = publish(env, (*payloads, *added))
    assert mixed[:3] == result and source_counts(env) == before + 5
    assert metadata(env, (*payloads, *added)) == mixed


@pytest.mark.parametrize("stage", ["upload", "receipts", "finalize"])
def test_interruption_never_partially_finalizes_and_replacement_resumes(
    publication, monkeypatch, stage,
):
    env, payloads = publication, writes(publication)
    target, method = {
        "upload": (env.objects, "put_if_absent"),
        "receipts": (env.publisher, "_record_receipts"),
        "finalize": (module, "finalize_batch"),
    }[stage]
    original, calls = getattr(target, method), 0

    def crash(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == (2 if stage == "upload" else 1):
            raise RuntimeError("lost batch acknowledgement")
        return result

    before = source_counts(env)
    with monkeypatch.context() as patch:
        patch.setattr(target, method, crash)
        with pytest.raises(RuntimeError, match="lost batch acknowledgement"):
            publish(env, payloads)
    rows = metadata(env, payloads)
    assert all(row.lifecycle_status == CloudArtifactPayloadLifecycleStatus.STAGED for row in rows)
    assert all(row.event_binding is None for row in rows)
    assert source_counts(env) == before
    assert all(row.lifecycle_revision == 0 and row.object_receipt is None for row in rows)
    _replace_worker(env)
    result = publish(env, payloads)
    assert all(row.lifecycle_revision == 2 for row in result)
    assert source_counts(env) == before + 3
    assert len(env.client.objects) == 3


@pytest.mark.parametrize("cause", ["revocation", "replacement", "mutation"])
def test_post_io_authority_and_lifecycle_failure_cannot_publish(
    publication, monkeypatch, cause,
):
    env, payloads = publication, writes(publication)
    original = env.objects.read_version_verified
    revoked, calls = False, 0

    def read(*args):
        nonlocal revoked, calls
        body = original(*args)
        calls += 1
        if calls == 3:
            if cause == "replacement":
                _replace_worker(env)
            elif cause == "mutation":
                with env.metadata._database.connect() as connection:
                    connection.execute(
                        """UPDATE artifact_payload_metadata SET mime_type='text/plain'
                           WHERE deployment_namespace=%s AND artifact_id=%s""",
                        (NAMESPACE, payloads[0][0]),
                    )
            revoked = True
        return body

    def check():
        if revoked and cause == "revocation":
            raise ValueError("revoked")

    monkeypatch.setattr(env.objects, "read_version_verified", read)
    before = source_counts(env)
    with pytest.raises((ValueError, LeaseLostError)):
        publish(env, payloads, check)
    assert source_counts(env) == before
    assert all(row.event_binding is None for row in metadata(env, payloads))


def test_duplicate_foreign_and_conflicting_batch_refuse_before_new_reservations(publication):
    env, payloads = publication, writes(publication)
    for invalid in ((), (payloads[0], payloads[0]), (
        (payloads[0][0], env.payload.model_copy(update={"session_id": uuid4()})),
    )):
        with pytest.raises(ValueError):
            publish(env, invalid)
    assert not env.client.objects and all(row is None for row in metadata(env, payloads))
    result = publish(env, payloads[:1])
    before = source_counts(env)
    conflict = ((payloads[0][0], env.payload), payloads[1])
    with pytest.raises(ValueError, match="immutable publication conflicts"):
        publish(env, conflict)
    assert source_counts(env) == before
    assert metadata(env, payloads) == (result[0], None, None)


def test_all_publication_phases_have_constant_query_count_per_batch(
    publication, monkeypatch, record_property,
):
    env = publication
    phase = ContextVar("batch_test_phase", default=None)
    counts = {"reserve": [], "receipts": [], "finalize": []}
    original = psycopg.Connection.execute
    current = {"calls": 0}

    def execute(connection, query, *args, **kwargs):
        if phase.get() is not None:
            current["calls"] += 1
        return original(connection, query, *args, **kwargs)

    def instrument(function, name):
        def measured(*args, **kwargs):
            current["calls"] = 0
            token = phase.set(name)
            try:
                return function(*args, **kwargs)
            finally:
                counts[name].append(current["calls"])
                phase.reset(token)
        return measured

    monkeypatch.setattr(psycopg.Connection, "execute", execute)
    monkeypatch.setattr(module, "reserve_batch", instrument(module.reserve_batch, "reserve"))
    monkeypatch.setattr(module, "record_receipts", instrument(module.record_receipts, "receipts"))
    monkeypatch.setattr(module, "finalize_batch", instrument(module.finalize_batch, "finalize"))
    for count in (1, 9):
        publish(env, writes(env, count))
    assert counts["reserve"][0] == counts["reserve"][1]
    assert counts["receipts"][0] == counts["receipts"][1]
    assert counts["finalize"][0] == counts["finalize"][1]
    record_property("artifact_stage_client_calls", json.dumps(counts))


def test_upload_and_verification_have_no_borrowed_database_transaction(publication, monkeypatch):
    from agent_storage.postgres.work_unit import borrow_work_unit

    env = publication
    phases = []
    for method in ("put_if_absent", "read_version_verified"):
        original = getattr(env.objects, method)

        def outside(*args, original=original, method=method, **kwargs):
            assert borrow_work_unit((env.dsn, NAMESPACE)) is None
            phases.append(method)
            return original(*args, **kwargs)

        monkeypatch.setattr(env.objects, method, outside)
    publish(env, writes(env))
    assert phases.count("put_if_absent") == phases.count("read_version_verified") == 3


@pytest.mark.parametrize("target", ["metadata", "event"])
def test_final_callback_same_transaction_mutation_rolls_back_whole_batch(publication, target):
    env, payloads = publication, writes(publication)
    calls = 0

    def check():
        nonlocal calls
        if (not calls and borrow_work_unit((env.dsn, NAMESPACE)) is not None
                and all(row.lifecycle_revision == 2 for row in metadata(env, payloads))):
            calls += 1
            with env.metadata._database.connect() as connection:
                if target == "metadata":
                    connection.execute(
                        """UPDATE artifact_payload_metadata SET file_name='changed'
                           WHERE deployment_namespace=%s AND artifact_id=%s""",
                        (NAMESPACE, payloads[0][0]),
                    )
                else:
                    connection.execute(
                        """UPDATE session_events SET payload=jsonb_set(payload,'{sha256}',%s)
                           WHERE deployment_namespace=%s AND event_id=(
                             SELECT event_id FROM artifact_payload_metadata
                             WHERE deployment_namespace=%s AND artifact_id=%s)""",
                        ('"' + "0" * 64 + '"', NAMESPACE, NAMESPACE, payloads[0][0]),
                    )

    before = source_counts(env)
    with pytest.raises(
        (ValueError, psycopg.errors.ObjectNotInPrerequisiteState),
        match="before final commit|projection metadata source is immutable",
    ):
        publish(env, payloads, check)
    assert calls == 1 and source_counts(env) == before
    rows = metadata(env, payloads)
    assert all(row.lifecycle_revision == 0 and row.event_binding is None
               and row.object_receipt is None for row in rows)
    assert all(row.reservation.file_name is None for row in rows)


def test_simultaneous_exact_publishers_converge_after_fresh_retry(publication, monkeypatch):
    env, payloads = publication, writes(publication)
    ready, committed, thread = Barrier(2), Event(), local()
    original = env.objects.put_if_absent

    def synchronized(request):
        if not getattr(thread, "prepared", False):
            thread.prepared = True
            ready.wait(timeout=10)
        return original(request)

    def attempt():
        for number in range(3):
            try:
                result = publish(env, payloads)
                committed.set()
                return result
            except CloudArtifactPayloadConflictError as error:
                assert str(error) in {
                    "artifact mutation stream revision is stale",
                    "coverage publication changed during object verification",
                    "coverage reservation batch raced",
                }
                if number == 2:
                    raise
                if getattr(thread, "prepared", False):
                    # After both uploads, wait for the winning atomic commit;
                    # immediate retries can exhaust before it leaves its I/O phase.
                    assert committed.wait(timeout=10)

    monkeypatch.setattr(env.objects, "put_if_absent", synchronized)
    before = source_counts(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results[0] == results[1] == metadata(env, payloads)
    assert source_counts(env) == before + 3 and len(env.client.objects) == 3
