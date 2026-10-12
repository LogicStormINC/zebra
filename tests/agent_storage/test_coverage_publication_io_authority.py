"""Fresh authority at each actual publisher I/O, with native transaction boundaries."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadConflictError
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres import coverage_artifact_publication as publication_module
from agent_storage.postgres.work_unit import borrow_work_unit

from tests.agent_storage.test_coverage_artifact_publication import (
    _authority,
    publication,  # noqa: F401
)
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, postgres_dsn  # noqa: F401
from tests.agent_storage.test_postgres_coverage import batch, dsn, source_counts  # noqa: F401
from tests.agent_storage.test_postgres_coverage import env as postgres_env  # noqa: F401


def _payloads(env):
    return (
        (env.artifact_id, env.payload),
        (ArtifactId(uuid4()), env.payload.model_copy(update={"payload": b'{"results":[2]}'})),
    )


def _metadata(env, payloads):
    return tuple(env.metadata.get_metadata(ArtifactMetadataQuery(
        deployment_namespace=NAMESPACE, session_id=env.session.session_id,
        artifact_id=identifier,
    )) for identifier, _ in payloads)


def _publish(env, payloads, check):
    return env.publisher.publish_batch(
        env.binding, payloads, authority=env.authority, check_authority=check,
    )


def _observe_io(env, monkeypatch, trace, callback=lambda *_: None):
    active = 0
    connect = env.publisher._database.connect

    @contextmanager
    def tracked_connect():
        nonlocal active
        with connect() as connection:
            active += 1
            try:
                yield connection
            finally:
                active -= 1

    monkeypatch.setattr(env.publisher._database, "connect", tracked_connect)

    def wrap(method):
        original = getattr(env.objects, method)

        def operation(*args):
            assert active == 0
            assert borrow_work_unit((env.dsn, NAMESPACE)) is None
            trace.append(method)
            result = original(*args)
            callback(method, args)
            return result

        monkeypatch.setattr(env.objects, method, operation)

    wrap("put_if_absent")
    wrap("read_version_verified")


@pytest.mark.parametrize("operation,resume", [
    ("put_if_absent", False), ("read_version_verified", False), ("read_version_verified", True),
])
def test_revocation_during_first_object_stops_all_later_io(
    publication, monkeypatch, operation, resume,  # noqa: F811
):
    env, trace = publication, []
    payloads = _payloads(env)
    if resume:
        record = env.publisher._record_receipts
        captured = []

        def crash_after_receipts(*args):
            captured.append(args)
            record(*args)
            raise RuntimeError("lost receipt acknowledgement")

        with monkeypatch.context() as patch:
            patch.setattr(env.publisher, "_record_receipts", crash_after_receipts)
            with pytest.raises(RuntimeError, match="lost receipt acknowledgement"):
                _publish(env, payloads, lambda: None)
        assert all(row.lifecycle_revision == 0 and row.object_receipt is None
                   for row in _metadata(env, payloads))
        # Legacy durable receipts remain readable. The standalone method hook
        # still owns its transaction; publish_batch now borrows its outer owner.
        record(*captured[0])
    before = source_counts(env)
    revoked = False

    def revoke(method, _args):
        nonlocal revoked
        if method == operation:
            revoked = True

    def check():
        trace.append("check")
        if revoked:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    _observe_io(env, monkeypatch, trace, revoke)
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        _publish(env, payloads, check)
    io = [item for item in trace if item != "check"]
    assert io == (["put_if_absent"] if operation == "put_if_absent" else
                  ["read_version_verified"] if resume else
                  ["put_if_absent", "read_version_verified"])
    assert trace[-1] == "check"
    staged = _metadata(env, payloads)
    assert all(row.lifecycle_status == "staged" and row.event_binding is None for row in staged)
    assert all(row.lifecycle_revision == (1 if resume else 0) for row in staged)
    assert all((row.object_receipt is not None) == resume for row in staged)
    assert len(env.client.objects) == (2 if resume else 1)
    assert source_counts(env) == before
    # Restored authority resumes deterministic bytes; no weak receipt/final ACK.
    records = _publish(env, payloads, lambda: None)
    assert all(row.lifecycle_status == "finalized" for row in records)
    assert source_counts(env) == before + 2
    assert len(env.client.objects) == 2


def test_every_fresh_and_replayed_io_has_distinct_pre_post_checks(
    publication, monkeypatch,  # noqa: F811
):
    env, trace = publication, []
    payloads = _payloads(env)
    _observe_io(env, monkeypatch, trace)
    before = source_counts(env)
    records = _publish(env, payloads, lambda: trace.append("check"))
    assert trace == ["check"] + [
        "check", "put_if_absent", "check", "check", "read_version_verified", "check",
    ] * 2 + ["check", "check"]
    assert source_counts(env) == before + 2
    trace.clear()
    assert _publish(env, payloads, lambda: trace.append("check")) == records
    assert trace == ["check"] + ["check", "read_version_verified", "check"] * 2 + [
        "check", "check",
    ]
    assert source_counts(env) == before + 2
    assert len(env.client.objects) == 2


@pytest.mark.parametrize("denied_check,dispatched", [(2, 0), (4, 1), (6, 2), (8, 3)])
def test_each_io_precheck_can_refuse_dispatch(
    publication, monkeypatch, denied_check, dispatched,  # noqa: F811
):
    env, trace = publication, []
    payloads = _payloads(env)
    before = source_counts(env)

    def check():
        trace.append("check")
        if trace.count("check") == denied_check:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    _observe_io(env, monkeypatch, trace)
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        _publish(env, payloads, check)
    assert len([item for item in trace if item != "check"]) == dispatched
    assert trace.count("check") == denied_check
    assert source_counts(env) == before
    assert all(row.lifecycle_status == "staged" and row.lifecycle_revision == 0
               and row.object_receipt is None and row.event_binding is None
               for row in _metadata(env, payloads))


def test_finalization_callback_rejection_rolls_back_receipts_and_events(
    publication, monkeypatch,  # noqa: F811
):
    env, trace = publication, []
    payloads, finalized = _payloads(env), False
    finalize = publication_module.finalize_batch
    before = source_counts(env)

    def revoke_after_finalize(*args):
        nonlocal finalized
        result = finalize(*args)
        assert all(row.lifecycle_status == "finalized" for row in result)
        finalized = True
        return result

    def check():
        trace.append("check")
        if finalized:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    _observe_io(env, monkeypatch, trace)
    monkeypatch.setattr(publication_module, "finalize_batch", revoke_after_finalize)
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        _publish(env, payloads, check)
    assert finalized
    assert source_counts(env) == before
    assert all(row.lifecycle_status == "staged" and row.lifecycle_revision == 0
               and row.object_receipt is None and row.event_binding is None
               for row in _metadata(env, payloads))
    records = _publish(env, payloads, lambda: None)
    assert all(row.lifecycle_status == "finalized" for row in records)
    assert source_counts(env) == before + 2


@pytest.mark.parametrize("fault", ["raise", "revoke"])
def test_receipt_hook_fault_rolls_back_atomic_publication_and_recovers_exact_versions(
    publication, monkeypatch, fault,  # noqa: F811
):
    env, trace = publication, []
    payloads = _payloads(env)
    before = source_counts(env)
    record = env.publisher._record_receipts
    revoked = False

    def check():
        trace.append("check")
        if revoked:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    def fail_after_record(*args):
        nonlocal revoked
        owner = borrow_work_unit((env.dsn, NAMESPACE))
        assert owner is not None
        result = record(*args)
        assert all(row.lifecycle_revision == 1 and row.object_receipt is not None
                   for row in result)
        assert not owner.unit.connection.closed
        # An independent connection cannot observe the borrowed receipt write.
        with ThreadPoolExecutor(max_workers=1) as observer:
            rows = observer.submit(_metadata, env, payloads).result()
            assert observer.submit(source_counts, env).result() == before
        assert all(row.lifecycle_revision == 0 and row.object_receipt is None for row in rows)
        if fault == "raise":
            raise RuntimeError("lost receipt acknowledgement")
        revoked = True
        return result

    _observe_io(env, monkeypatch, trace)
    with monkeypatch.context() as patch:
        patch.setattr(env.publisher, "_record_receipts", fail_after_record)
        error = RuntimeError if fault == "raise" else CoverageRefusedError
        message = "lost receipt acknowledgement" if fault == "raise" else "authority_invalid"
        with pytest.raises(error, match=message):
            _publish(env, payloads, check)
    assert source_counts(env) == before
    assert all(row.lifecycle_revision == 0 and row.object_receipt is None
               and row.event_binding is None for row in _metadata(env, payloads))
    versions = dict(env.client.objects)
    assert len(versions) == 2
    records = _publish(env, payloads, lambda: None)
    assert dict(env.client.objects) == versions
    assert all(row.lifecycle_status == "finalized" and row.lifecycle_revision == 2
               for row in records)
    assert source_counts(env) == before + 2


def test_post_upload_uses_one_owner_and_locks_before_receipt_settlement(
    publication, monkeypatch,  # noqa: F811
):
    env, owners, order = publication, [], []
    payloads = _payloads(env)
    lock, record, finalize = (
        publication_module.lock_run, publication_module.record_receipts,
        publication_module.finalize_batch,
    )
    connect = env.publisher._database.connect
    physical = []

    @contextmanager
    def observed_connect():
        borrowed = borrow_work_unit((env.dsn, NAMESPACE))
        with connect() as connection:
            if borrowed is None:
                physical.append(connection)
            yield connection

    def lock_first(connection, *args):
        order.append("lock")
        result = lock(connection, *args)
        owners.append((connection, result[1]))
        return result

    def borrowed_record(connection, *args):
        order.append("receipt")
        assert connection.unit.connection is owners[0][0]
        assert borrow_work_unit((env.dsn, NAMESPACE)).unit.connection is owners[0][0]
        return record(connection, *args)

    def finalize_owned(connection, *args):
        order.append("finalize")
        assert connection is owners[0][0] and args[-1] == owners[0][1]
        return finalize(connection, *args)

    monkeypatch.setattr(env.publisher._database, "connect", observed_connect)
    monkeypatch.setattr(publication_module, "lock_run", lock_first)
    monkeypatch.setattr(publication_module, "record_receipts", borrowed_record)
    monkeypatch.setattr(publication_module, "finalize_batch", finalize_owned)
    records = _publish(env, payloads, lambda: None)
    assert order == ["lock", "receipt", "finalize"]
    assert len(physical) == 2  # Reservation, then one atomic post-upload transaction.
    assert all(connection.closed for connection in physical)
    assert _metadata(env, payloads) == records


@pytest.mark.parametrize("mismatch", ["lease", "version"])
def test_post_upload_native_mismatch_cannot_record_finalize_or_charge(
    publication, monkeypatch, mismatch,  # noqa: F811
):
    env, trace = publication, []
    payloads = _payloads(env)
    before = source_counts(env)
    changed = False

    def change_boundary(method, _args):
        nonlocal changed
        if method != "read_version_verified" or trace.count(method) != 2:
            return
        changed = True
        if mismatch == "lease":
            env.leases.release(env.session.session_id, fence=env.fence)
            replacement = env.leases.acquire(
                env.session.session_id, owner_instance_id="publication-replacement",
                ttl=timedelta(minutes=5),
            )
            env.fence = replacement.fence
        else:
            env.store.commit(batch(env), fence=env.fence)

    def charges():
        with env.publisher._database.connect() as connection:
            return connection.execute(
                """SELECT calls,charged_tokens,unresolved FROM coverage_model_ledger
                   WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
                (NAMESPACE, env.binding.namespace, env.binding.run_id),
            ).fetchall()

    initial_charges = charges()
    _observe_io(env, monkeypatch, trace, change_boundary)
    error = LeaseLostError if mismatch == "lease" else CloudArtifactPayloadConflictError
    with pytest.raises(error):
        _publish(env, payloads, lambda: None)
    assert changed
    assert source_counts(env) == before + (mismatch == "version")
    assert charges() == initial_charges
    assert all(row.lifecycle_revision == 0 and row.object_receipt is None
               and row.event_binding is None for row in _metadata(env, payloads))
    with env.publisher._database.connect() as connection:
        assert connection.execute(
            """SELECT count(*) AS count FROM artifact_payload_mutations
               WHERE deployment_namespace=%s AND artifact_id=ANY(%s)
                 AND operation_kind IN ('record_object','finalize')""",
            (NAMESPACE, [identifier for identifier, _ in payloads]),
        ).fetchone()["count"] == 0
    versions = dict(env.client.objects)
    env.authority = _authority(env)
    records = _publish(env, payloads, lambda: None)
    assert all(row.lifecycle_status == "finalized" for row in records)
    assert dict(env.client.objects) == versions
    assert charges() == initial_charges
    assert source_counts(env) == before + (mismatch == "version") + 2
