from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectCleanupEvidence,
    ArtifactObjectDeleteRequest,
    ArtifactObjectDeleteResult,
    ArtifactObjectDeleteStatus,
    ArtifactObjectExpectation,
    ArtifactObjectReceipt,
    ArtifactObjectVerification,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadConflictError,
    CloudArtifactPayloadLifecycleStatus,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactBeginPruneRequest,
    ArtifactCompensateRequest,
    ArtifactCompletePruneRequest,
    ArtifactEventBinding,
    ArtifactFinalizeRequest,
    ArtifactMetadataQuery,
    ArtifactRecordObjectRequest,
    ArtifactReserveRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId, new_artifact_id, new_session_id
from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_core.ports import WorkerMutationAuthority
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    PostgresLeaseStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"artifact_payload_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_reserve_persists_complete_staged_metadata_and_replays(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    request = _reservation(session_id)
    authority = _authority(namespace, session_id, lease, revision=0)

    first = store.reserve_for_worker(request, authority=authority)
    second = store.reserve_for_worker(request, authority=authority)

    assert first == second
    assert first.deployment_namespace == namespace
    assert first.reservation == request
    assert first.lifecycle_status is CloudArtifactPayloadLifecycleStatus.STAGED
    assert first.lifecycle_revision == 0
    assert first.object_receipt is None
    assert first.event_binding is None
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT reservation_epoch, reservation_fencing_token,
                   reservation_owner_instance_id, count(*) OVER () AS row_count
            FROM artifact_payload_metadata
            """
        ).fetchone()
    assert row == (
        lease.fence.control_plane_epoch,
        lease.fence.fencing_token,
        lease.fence.owner_instance_id,
        1,
    )


def test_get_metadata_is_fully_scoped(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    request = _reservation(session_id)
    stored = store.reserve_for_worker(
        request,
        authority=_authority(namespace, session_id, lease, revision=0),
    )

    assert store.get_metadata(_query(namespace, request.artifact_id, session_id)) == stored
    assert store.get_metadata(_query("other", request.artifact_id, session_id)) is None
    assert store.get_metadata(
        _query(namespace, request.artifact_id, new_session_id())
    ) is None


def test_reserve_rejects_changed_idempotent_retry_and_artifact_collision(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    request = _reservation(session_id)
    authority = _authority(namespace, session_id, lease, revision=0)
    stored = store.reserve_for_worker(request, authority=authority)

    changed = request.model_copy(update={"kind": "different"})
    with pytest.raises(CloudArtifactPayloadConflictError):
        store.reserve_for_worker(changed, authority=authority)
    colliding = request.model_copy(update={"idempotency_key": "another-key"})
    with pytest.raises(CloudArtifactPayloadConflictError):
        store.reserve_for_worker(colliding, authority=authority)

    assert store.get_metadata(_query(namespace, request.artifact_id, session_id)) == stored
    assert _metadata_count(dsn) == 1


def test_reserve_rejects_stale_authority_without_writes(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    request = _reservation(session_id)
    authority = _authority(namespace, session_id, lease, revision=0)

    stale_fence = authority.model_copy(
        update={"lease_fence": lease.fence.model_copy(update={"fencing_token": 99})}
    )
    with pytest.raises(LeaseLostError):
        store.reserve_for_worker(request, authority=stale_fence)
    stale_stream = authority.model_copy(update={"expected_stream_revision": -1})
    stale_request = request.model_copy(update={"intended_event_sequence": 0})
    with pytest.raises(CloudArtifactPayloadConflictError):
        store.reserve_for_worker(stale_request, authority=stale_stream)
    with pytest.raises(LeaseLostError):
        store.reserve_for_worker(
            request,
            authority=authority.model_copy(update={"deployment_namespace": "other"}),
        )
    assert _metadata_count(dsn) == 0


def test_concurrent_identical_reservations_create_one_row(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    request = _reservation(session_id)
    authority = _authority(namespace, session_id, lease, revision=0)

    def reserve() -> object:
        return PostgresCloudArtifactPayloadStore(
            dsn,
            deployment_namespace=namespace,
        ).reserve_for_worker(request, authority=authority)

    with ThreadPoolExecutor(max_workers=2) as executor:
        records = tuple(executor.map(lambda _: reserve(), range(2)))

    assert records[0] == records[1]
    assert _metadata_count(dsn) == 1


def test_record_object_and_finalize_bind_canonical_event(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    reservation = _reservation(session_id)
    before_event = _authority(namespace, session_id, lease, revision=0)
    store.reserve_for_worker(reservation, authority=before_event)
    receipt = _receipt(namespace, reservation)

    recorded = store.record_object_for_worker(
        ArtifactRecordObjectRequest(
            artifact_id=reservation.artifact_id,
            session_id=session_id,
            expected_lifecycle_revision=0,
            idempotency_key="record-1",
            object_receipt=receipt,
        ),
        authority=before_event,
    )
    event = _artifact_event(reservation)
    PostgresEventStore(dsn, deployment_namespace=namespace).append(event)
    finalize_request = ArtifactFinalizeRequest(
        artifact_id=reservation.artifact_id,
        session_id=session_id,
        expected_lifecycle_revision=1,
        idempotency_key="finalize-1",
        event_binding=ArtifactEventBinding(
            session_id=session_id,
            event_id=event.event_id,
            sequence=event.sequence,
            artifact_uri=f"artifact://{reservation.artifact_id}",
        ),
        object_receipt=receipt,
        finalized_at=datetime.now(UTC),
    )
    after_event = _authority(namespace, session_id, lease, revision=1)
    finalized = store.finalize_for_worker(finalize_request, authority=after_event)
    replay = store.finalize_for_worker(finalize_request, authority=after_event)

    assert recorded.lifecycle_revision == 1
    assert recorded.object_receipt == receipt
    assert finalized == replay
    assert finalized.lifecycle_status is CloudArtifactPayloadLifecycleStatus.FINALIZED
    assert finalized.lifecycle_revision == 2
    assert finalized.event_binding == finalize_request.event_binding
    assert _mutation_count(dsn) == 2


def test_finalize_rejects_event_without_canonical_artifact_uri(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    reservation = _reservation(session_id)
    before_event = _authority(namespace, session_id, lease, revision=0)
    store.reserve_for_worker(reservation, authority=before_event)
    receipt = _receipt(namespace, reservation)
    store.record_object_for_worker(
        ArtifactRecordObjectRequest(
            artifact_id=reservation.artifact_id,
            session_id=session_id,
            expected_lifecycle_revision=0,
            idempotency_key="record-1",
            object_receipt=receipt,
        ),
        authority=before_event,
    )
    event = _artifact_event(reservation, artifact_uri="artifact://unrelated")
    PostgresEventStore(dsn, deployment_namespace=namespace).append(event)
    request = ArtifactFinalizeRequest(
        artifact_id=reservation.artifact_id,
        session_id=session_id,
        expected_lifecycle_revision=1,
        idempotency_key="finalize-1",
        event_binding=ArtifactEventBinding(
            session_id=session_id,
            event_id=event.event_id,
            sequence=1,
            artifact_uri=f"artifact://{reservation.artifact_id}",
        ),
        object_receipt=receipt,
        finalized_at=datetime.now(UTC),
    )

    with pytest.raises(CloudArtifactPayloadConflictError):
        store.finalize_for_worker(
            request,
            authority=_authority(namespace, session_id, lease, revision=1),
        )
    current = store.get_metadata(_query(namespace, reservation.artifact_id, session_id))
    assert current is not None
    assert current.lifecycle_status is CloudArtifactPayloadLifecycleStatus.STAGED
    assert current.lifecycle_revision == 1
    assert _mutation_count(dsn) == 1


def test_compensate_requires_absent_event_and_object_proof(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    reservation = _reservation(session_id)
    authority = _authority(namespace, session_id, lease, revision=0)
    store.reserve_for_worker(reservation, authority=authority)
    request = ArtifactCompensateRequest(
        artifact_id=reservation.artifact_id,
        session_id=session_id,
        expected_lifecycle_revision=0,
        idempotency_key="compensate-1",
        object_cleanup=ArtifactObjectCleanupEvidence(
            verification=ArtifactObjectVerification(
                expectation=_expectation(namespace, reservation),
                status=ArtifactObjectVerificationStatus.NOT_FOUND,
            )
        ),
        compensated_at=datetime.now(UTC),
    )

    compensated = store.compensate_for_worker(request, authority=authority)
    replay = store.compensate_for_worker(request, authority=authority)
    assert compensated == replay
    assert compensated.lifecycle_status is CloudArtifactPayloadLifecycleStatus.COMPENSATED
    assert compensated.lifecycle_revision == 1


def test_compensate_fails_when_reserved_event_slot_is_occupied(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    reservation = _reservation(session_id)
    store.reserve_for_worker(
        reservation,
        authority=_authority(namespace, session_id, lease, revision=0),
    )
    PostgresEventStore(dsn, deployment_namespace=namespace).append(
        _artifact_event(reservation, artifact_uri="artifact://unrelated")
    )
    request = ArtifactCompensateRequest(
        artifact_id=reservation.artifact_id,
        session_id=session_id,
        expected_lifecycle_revision=0,
        idempotency_key="compensate-1",
        object_cleanup=ArtifactObjectCleanupEvidence(
            verification=ArtifactObjectVerification(
                expectation=_expectation(namespace, reservation),
                status=ArtifactObjectVerificationStatus.NOT_FOUND,
            )
        ),
        compensated_at=datetime.now(UTC),
    )

    with pytest.raises(CloudArtifactPayloadConflictError):
        store.compensate_for_worker(
            request,
            authority=_authority(namespace, session_id, lease, revision=1),
        )
    assert _mutation_count(dsn) == 0


def test_worker_prune_is_exact_versioned_and_idempotent(dsn: str) -> None:
    namespace, session_id, lease = _prepared_worker(dsn)
    store = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    reservation = _reservation(session_id)
    before_event = _authority(namespace, session_id, lease, revision=0)
    store.reserve_for_worker(reservation, authority=before_event)
    receipt = _receipt(namespace, reservation)
    store.record_object_for_worker(
        ArtifactRecordObjectRequest(
            artifact_id=reservation.artifact_id,
            session_id=session_id,
            expected_lifecycle_revision=0,
            idempotency_key="record-1",
            object_receipt=receipt,
        ),
        authority=before_event,
    )
    event = _artifact_event(reservation)
    PostgresEventStore(dsn, deployment_namespace=namespace).append(event)
    after_event = _authority(namespace, session_id, lease, revision=1)
    store.finalize_for_worker(
        ArtifactFinalizeRequest(
            artifact_id=reservation.artifact_id,
            session_id=session_id,
            expected_lifecycle_revision=1,
            idempotency_key="finalize-1",
            event_binding=ArtifactEventBinding(
                session_id=session_id,
                event_id=event.event_id,
                sequence=1,
                artifact_uri=f"artifact://{reservation.artifact_id}",
            ),
            object_receipt=receipt,
            finalized_at=datetime.now(UTC),
        ),
        authority=after_event,
    )
    begin_request = ArtifactBeginPruneRequest(
        artifact_id=reservation.artifact_id,
        session_id=session_id,
        expected_lifecycle_revision=2,
        idempotency_key="begin-prune-1",
        requested_at=datetime.now(UTC),
    )
    pruning = store.begin_prune_for_worker(begin_request, authority=after_event)
    assert store.begin_prune_for_worker(begin_request, authority=after_event) == pruning
    complete_request = ArtifactCompletePruneRequest(
        artifact_id=reservation.artifact_id,
        session_id=session_id,
        expected_lifecycle_revision=3,
        idempotency_key="complete-prune-1",
        object_delete=ArtifactObjectDeleteResult(
            request=ArtifactObjectDeleteRequest(
                expectation=_expectation(namespace, reservation),
                object_version=receipt.object_version,
            ),
            status=ArtifactObjectDeleteStatus.DELETED,
        ),
        pruned_at=datetime.now(UTC),
    )
    pruned = store.complete_prune_for_worker(complete_request, authority=after_event)

    assert pruning.lifecycle_status is CloudArtifactPayloadLifecycleStatus.PRUNING
    assert pruning.lifecycle_revision == 3
    assert pruned.lifecycle_status is CloudArtifactPayloadLifecycleStatus.PRUNED
    assert pruned.lifecycle_revision == 4
    assert store.complete_prune_for_worker(complete_request, authority=after_event) == pruned
    assert _mutation_count(dsn) == 4


def _prepared_worker(dsn: str) -> tuple[str, SessionId, WorkerLease]:
    namespace = f"artifact-{uuid4()}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    session_id = new_session_id()
    PostgresEventStore(dsn, deployment_namespace=namespace).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "Artifact test"},
            created_at=NOW,
        )
    )
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id,
        owner_instance_id="artifact-worker",
        ttl=timedelta(minutes=5),
    )
    return namespace, session_id, lease


def _reservation(session_id: SessionId) -> ArtifactReserveRequest:
    payload = b"artifact payload"
    return ArtifactReserveRequest(
        artifact_id=new_artifact_id(),
        session_id=session_id,
        intended_event_sequence=1,
        kind="tool-output",
        mime_type="text/plain",
        sha256=sha256(payload).hexdigest(),
        size_bytes=len(payload),
        idempotency_key="artifact-reserve-1",
        file_name="result.txt",
        retained_until=NOW + timedelta(days=30),
        created_at=NOW,
    )


def _authority(
    namespace: str,
    session_id: SessionId,
    lease: WorkerLease,
    *,
    revision: int,
) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=session_id,
        expected_stream_revision=revision,
        lease_fence=lease.fence,
    )


def _expectation(
    namespace: str,
    reservation: ArtifactReserveRequest,
) -> ArtifactObjectExpectation:
    return ArtifactObjectExpectation(
        deployment_namespace=namespace,
        artifact_id=reservation.artifact_id,
        sha256=reservation.sha256,
        size_bytes=reservation.size_bytes,
    )


def _receipt(
    namespace: str,
    reservation: ArtifactReserveRequest,
) -> ArtifactObjectReceipt:
    return ArtifactObjectReceipt(
        expectation=_expectation(namespace, reservation),
        object_version="object-version-1",
        verified_at=datetime.now(UTC),
    )


def _artifact_event(
    reservation: ArtifactReserveRequest,
    *,
    artifact_uri: str | None = None,
) -> SessionEvent:
    return SessionEvent.create(
        session_id=reservation.session_id,
        sequence=reservation.intended_event_sequence,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "files.read",
            "status": "executed",
            "output": "stored externally",
            "metadata": {
                "artifact_uri": artifact_uri or f"artifact://{reservation.artifact_id}"
            },
        },
        created_at=datetime.now(UTC),
    )


def _query(
    namespace: str,
    artifact_id: ArtifactId,
    session_id: SessionId,
) -> ArtifactMetadataQuery:
    return ArtifactMetadataQuery(
        deployment_namespace=namespace,
        artifact_id=artifact_id,
        session_id=session_id,
    )


def _metadata_count(dsn: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute("SELECT count(*) FROM artifact_payload_metadata").fetchone()
    assert row is not None
    return int(row[0])


def _mutation_count(dsn: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute("SELECT count(*) FROM artifact_payload_mutations").fetchone()
    assert row is not None
    return int(row[0])
