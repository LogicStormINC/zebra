from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.artifact_objects import ArtifactObjectExpectation, ArtifactObjectReceipt
from agent_core.domain.cloud_artifact_payloads import (
    CloudArtifactPayloadLifecycleStatus,
    CloudArtifactPayloadRecord,
)
from agent_core.domain.cloud_artifact_requests import (
    ArtifactEventBinding,
    ArtifactFinalizeRequest,
    ArtifactManagementContext,
    ArtifactMetadataQuery,
    ArtifactReconcileQuery,
    ArtifactRecordObjectRequest,
    ArtifactReserveRequest,
)
from agent_core.domain.effect_dispatch import (
    EffectDispatchConflictError,
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import (
    SessionId,
    new_artifact_id,
    new_event_id,
    new_session_id,
    new_tool_call_id,
)
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS, WorkerMutationAuthority
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEffectDispatchStore,
    PostgresEventStore,
    PostgresLeaseStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"effect_payload_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_schedule_with_payload_atomically_finalizes_event_and_outbox(dsn: str) -> None:
    namespace, session_id, authority = _prepared_worker(dsn)
    artifacts = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    effects = PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)
    reservation, receipt = _stage_payload(artifacts, authority, sequence=1)
    started = _artifact_event(reservation, EventType.TOOL_EXECUTION_STARTED)
    request = _schedule_request(session_id, started, reservation)
    finalize = _finalize(reservation, receipt, started)

    dispatch = effects.schedule_with_payload(
        request,
        authority=authority,
        artifact_finalize=finalize,
    )

    assert dispatch.status is EffectDispatchStatus.PENDING
    assert dispatch.payload_artifact_ref == f"artifact://{reservation.artifact_id}"
    assert _metadata(artifacts, namespace, reservation).lifecycle_status is (
        CloudArtifactPayloadLifecycleStatus.FINALIZED
    )
    assert (
        PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id)[-1]
        == started
    )
    assert _effect_status(dsn) == "pending"

    replay_event = started.model_copy(update={"event_id": new_event_id()})
    replay = effects.schedule_with_payload(
        request.model_copy(update={"started_event": replay_event}),
        authority=authority,
        artifact_finalize=finalize,
    )
    assert replay == dispatch

    with pytest.raises(LeaseLostError):
        effects.schedule_with_payload(
            request,
            authority=authority.model_copy(update={"session_id": new_session_id()}),
            artifact_finalize=finalize,
        )

    with pytest.raises(EffectDispatchConflictError):
        effects.schedule_with_payload(
            request.model_copy(update={"payload_artifact_ref": "artifact://different"}),
            authority=authority,
            artifact_finalize=finalize,
        )


def test_unknown_schedule_response_keeps_payload_for_durable_replay(dsn: str) -> None:
    namespace, session_id, authority = _prepared_worker(dsn)
    artifacts = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    effects = PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)
    reservation, receipt = _stage_payload(artifacts, authority, sequence=1)
    started = _artifact_event(reservation, EventType.TOOL_EXECUTION_STARTED)
    request = _schedule_request(session_id, started, reservation)
    finalize = _finalize(reservation, receipt, started)

    def lose_response_after_commit() -> None:
        effects.schedule_with_payload(
            request,
            authority=authority,
            artifact_finalize=finalize,
        )
        raise ConnectionError("response lost after commit")

    with pytest.raises(ConnectionError, match="response lost"):
        lose_response_after_commit()

    persisted = _metadata(artifacts, namespace, reservation)
    assert persisted.lifecycle_status is CloudArtifactPayloadLifecycleStatus.FINALIZED
    assert persisted.object_receipt == receipt
    assert _effect_count(dsn) == 1
    assert (
        len(PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id))
        == 2
    )
    assert (
        effects.schedule_with_payload(
            request.model_copy(
                update={"started_event": started.model_copy(update={"event_id": new_event_id()})}
            ),
            authority=authority,
            artifact_finalize=finalize,
        ).status
        is EffectDispatchStatus.PENDING
    )


def test_initial_stale_fence_reserves_no_payload_or_effect_state(dsn: str) -> None:
    namespace, session_id, authority = _prepared_worker(dsn)
    artifacts = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    reservation = _reservation(authority, sequence=1)
    stale = authority.model_copy(
        update={
            "lease_fence": authority.lease_fence.model_copy(
                update={"fencing_token": authority.lease_fence.fencing_token + 1}
            )
        }
    )

    with pytest.raises(LeaseLostError):
        artifacts.reserve_for_worker(reservation, authority=stale)

    assert _metadata_count(dsn) == 0
    assert _effect_count(dsn) == 0
    assert (
        len(PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id))
        == 1
    )


def test_mid_flight_takeover_keeps_staged_payload_reconcilable(dsn: str) -> None:
    namespace, session_id, authority = _prepared_worker(dsn)
    artifacts = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    effects = PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)
    reservation, receipt = _stage_payload(artifacts, authority, sequence=1)
    started = _artifact_event(reservation, EventType.TOOL_EXECUTION_STARTED)
    leases = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    leases.release(session_id, fence=authority.lease_fence)
    leases.acquire(
        session_id,
        owner_instance_id="takeover-worker",
        ttl=timedelta(minutes=5),
    )

    with pytest.raises(LeaseLostError):
        effects.schedule_with_payload(
            _schedule_request(session_id, started, reservation),
            authority=authority,
            artifact_finalize=_finalize(reservation, receipt, started),
        )

    assert _effect_count(dsn) == 0
    staged = _metadata(artifacts, namespace, reservation)
    assert staged.lifecycle_status is CloudArtifactPayloadLifecycleStatus.STAGED
    assert staged.object_receipt == receipt
    assert (
        len(PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id))
        == 1
    )
    reconcilable = artifacts.list_reconcilable(
        ArtifactReconcileQuery(older_than=datetime.now(UTC) + timedelta(seconds=1)),
        authority=AdministrativeMutationCAS(
            deployment_namespace=namespace,
            session_id=session_id,
            expected_stream_revision=0,
        ),
        audit=ArtifactManagementContext(
            operation_id=uuid4(),
            operator_id="artifact-reconciler",
            reason="inspect payload staged before effect scheduling takeover",
        ),
    )
    assert tuple(record.artifact_id for record in reconcilable) == (reservation.artifact_id,)


@pytest.mark.parametrize("uncertain", [False, True])
def test_terminal_with_payload_commits_one_event_artifact_and_effect_state(
    dsn: str,
    *,
    uncertain: bool,
) -> None:
    namespace, session_id, initial_authority = _prepared_worker(dsn)
    artifacts = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    effects = PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)
    input_reservation, input_receipt = _stage_payload(
        artifacts,
        initial_authority,
        sequence=1,
    )
    started = _artifact_event(input_reservation, EventType.TOOL_EXECUTION_STARTED)
    effects.schedule_with_payload(
        _schedule_request(session_id, started, input_reservation),
        authority=initial_authority,
        artifact_finalize=_finalize(input_reservation, input_receipt, started),
    )
    claim = effects.claim_next(
        session_id,
        fence=initial_authority.lease_fence,
        claim_ttl=timedelta(minutes=1),
    )
    assert claim is not None
    terminal_authority = initial_authority.model_copy(update={"expected_stream_revision": 1})
    output_reservation, output_receipt = _stage_payload(
        artifacts,
        terminal_authority,
        sequence=2,
    )
    event_type = (
        EventType.TOOL_EXECUTION_FAILED if uncertain else EventType.TOOL_EXECUTION_COMPLETED
    )
    terminal = _artifact_event(output_reservation, event_type)

    if uncertain:
        persisted = effects.mark_uncertain_with_payload(
            claim,
            evidence=EffectEvidence(reason_code="provider_result_ambiguous"),
            terminal_event=terminal,
            authority=terminal_authority,
            artifact_finalize=_finalize(output_reservation, output_receipt, terminal),
        )
        expected_status = "uncertain"
    else:
        persisted = effects.complete_with_payload(
            claim,
            result=_result(),
            terminal_event=terminal,
            authority=terminal_authority,
            artifact_finalize=_finalize(output_reservation, output_receipt, terminal),
        )
        expected_status = "succeeded"

    assert persisted == terminal
    assert _effect_status(dsn) == expected_status
    assert _metadata(artifacts, namespace, output_reservation).lifecycle_status is (
        CloudArtifactPayloadLifecycleStatus.FINALIZED
    )
    assert (
        len(PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id))
        == 3
    )


def test_terminal_payload_binding_failure_rolls_back_all_three_writes(dsn: str) -> None:
    namespace, session_id, initial_authority = _prepared_worker(dsn)
    artifacts = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    effects = PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)
    input_reservation, input_receipt = _stage_payload(
        artifacts,
        initial_authority,
        sequence=1,
    )
    started = _artifact_event(input_reservation, EventType.TOOL_EXECUTION_STARTED)
    effects.schedule_with_payload(
        _schedule_request(session_id, started, input_reservation),
        authority=initial_authority,
        artifact_finalize=_finalize(input_reservation, input_receipt, started),
    )
    claim = effects.claim_next(
        session_id,
        fence=initial_authority.lease_fence,
        claim_ttl=timedelta(minutes=1),
    )
    assert claim is not None
    terminal_authority = initial_authority.model_copy(update={"expected_stream_revision": 1})
    reservation, receipt = _stage_payload(artifacts, terminal_authority, sequence=2)
    terminal = _artifact_event(reservation, EventType.TOOL_EXECUTION_COMPLETED)
    conflicting = _finalize(reservation, receipt, terminal).model_copy(
        update={
            "event_binding": _finalize(reservation, receipt, terminal).event_binding.model_copy(
                update={"event_id": new_event_id()}
            )
        }
    )

    with pytest.raises(EffectDispatchStateError, match="does not bind"):
        effects.complete_with_payload(
            claim,
            result=_result(),
            terminal_event=terminal,
            authority=terminal_authority,
            artifact_finalize=conflicting,
        )

    assert _effect_status(dsn) == "claimed"
    assert _metadata(artifacts, namespace, reservation).lifecycle_status is (
        CloudArtifactPayloadLifecycleStatus.STAGED
    )
    assert _metadata(artifacts, namespace, reservation).object_receipt == receipt
    assert (
        len(PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id))
        == 2
    )
    reconcilable = artifacts.list_reconcilable(
        ArtifactReconcileQuery(older_than=datetime.now(UTC) + timedelta(seconds=1)),
        authority=AdministrativeMutationCAS(
            deployment_namespace=namespace,
            session_id=session_id,
            expected_stream_revision=1,
        ),
        audit=ArtifactManagementContext(
            operation_id=uuid4(),
            operator_id="artifact-reconciler",
            reason="inspect payload after terminal transaction rollback",
        ),
    )
    assert tuple(record.artifact_id for record in reconcilable) == (reservation.artifact_id,)


def test_stale_terminal_payload_becomes_uncertain_without_replay(dsn: str) -> None:
    namespace, session_id, initial_authority = _prepared_worker(dsn)
    artifacts = PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=namespace)
    effects = PostgresEffectDispatchStore(dsn, deployment_namespace=namespace)
    input_reservation, input_receipt = _stage_payload(
        artifacts,
        initial_authority,
        sequence=1,
    )
    started = _artifact_event(input_reservation, EventType.TOOL_EXECUTION_STARTED)
    effects.schedule_with_payload(
        _schedule_request(session_id, started, input_reservation),
        authority=initial_authority,
        artifact_finalize=_finalize(input_reservation, input_receipt, started),
    )
    claim = effects.claim_next(
        session_id,
        fence=initial_authority.lease_fence,
        claim_ttl=timedelta(minutes=1),
    )
    assert claim is not None
    terminal_authority = initial_authority.model_copy(update={"expected_stream_revision": 1})
    output_reservation, output_receipt = _stage_payload(
        artifacts,
        terminal_authority,
        sequence=2,
    )
    terminal = _artifact_event(output_reservation, EventType.TOOL_EXECUTION_COMPLETED)
    leases = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    leases.release(session_id, fence=initial_authority.lease_fence)
    takeover = leases.acquire(
        session_id,
        owner_instance_id="takeover-worker",
        ttl=timedelta(minutes=5),
    )

    with pytest.raises(LeaseLostError):
        effects.complete_with_payload(
            claim,
            result=_result(),
            terminal_event=terminal,
            authority=terminal_authority,
            artifact_finalize=_finalize(output_reservation, output_receipt, terminal),
        )

    assert _effect_status(dsn) == "claimed"
    assert _metadata(artifacts, namespace, output_reservation).lifecycle_status is (
        CloudArtifactPayloadLifecycleStatus.STAGED
    )
    assert len(PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id)) == 2
    reconcilable = effects.list_reconcilable(
        session_id,
        current_fence=takeover.fence,
    )
    assert len(reconcilable) == 1
    resolved = effects.reconcile_expired(
        reconcilable[0].dispatch.dispatch_id,
        old_claim=reconcilable[0],
        current_fence=takeover.fence,
        evidence=EffectEvidence(reason_code="lease_lost_after_provider_success"),
    )

    assert resolved.status is EffectDispatchStatus.UNCERTAIN
    assert _effect_status(dsn) == "uncertain"
    assert len(PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id)) == 2


def _prepared_worker(dsn: str) -> tuple[str, SessionId, WorkerMutationAuthority]:
    namespace = f"effect-payload-{uuid4()}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    session_id = new_session_id()
    PostgresEventStore(dsn, deployment_namespace=namespace).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "Effect payload test"},
        )
    )
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id,
        owner_instance_id="effect-payload-worker",
        ttl=timedelta(minutes=5),
    )
    return (
        namespace,
        session_id,
        WorkerMutationAuthority(
            deployment_namespace=namespace,
            session_id=session_id,
            expected_stream_revision=0,
            lease_fence=lease.fence,
        ),
    )


def _stage_payload(
    store: PostgresCloudArtifactPayloadStore,
    authority: WorkerMutationAuthority,
    *,
    sequence: int,
) -> tuple[ArtifactReserveRequest, ArtifactObjectReceipt]:
    reservation = _reservation(authority, sequence=sequence)
    store.reserve_for_worker(reservation, authority=authority)
    receipt = ArtifactObjectReceipt(
        expectation=ArtifactObjectExpectation(
            deployment_namespace=authority.deployment_namespace,
            artifact_id=reservation.artifact_id,
            sha256=reservation.sha256,
            size_bytes=reservation.size_bytes,
        ),
        object_version=f"version-{sequence}",
        verified_at=datetime.now(UTC),
    )
    store.record_object_for_worker(
        ArtifactRecordObjectRequest(
            artifact_id=reservation.artifact_id,
            session_id=authority.session_id,
            expected_lifecycle_revision=0,
            idempotency_key=f"effect-payload-record-{sequence}",
            object_receipt=receipt,
        ),
        authority=authority,
    )
    return reservation, receipt


def _reservation(
    authority: WorkerMutationAuthority,
    *,
    sequence: int,
) -> ArtifactReserveRequest:
    payload = f"payload-{sequence}".encode()
    return ArtifactReserveRequest(
        artifact_id=new_artifact_id(),
        session_id=authority.session_id,
        intended_event_sequence=sequence,
        kind="effect_tool_call",
        mime_type="application/json",
        sha256=sha256(payload).hexdigest(),
        size_bytes=len(payload),
        idempotency_key=f"effect-payload-reserve-{sequence}",
        file_name="tool-call.json",
        created_at=datetime.now(UTC),
    )


def _artifact_event(
    reservation: ArtifactReserveRequest,
    event_type: EventType,
) -> SessionEvent:
    return SessionEvent.create(
        session_id=reservation.session_id,
        sequence=reservation.intended_event_sequence,
        event_type=event_type,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": "publish",
            "status": "failed" if event_type is EventType.TOOL_EXECUTION_FAILED else "executed",
            "output": "",
            "metadata": {"artifact_uri": f"artifact://{reservation.artifact_id}"},
        },
        idempotency_key=f"effect-event-{reservation.intended_event_sequence}",
    )


def _schedule_request(
    session_id: SessionId,
    started: SessionEvent,
    reservation: ArtifactReserveRequest,
) -> EffectScheduleRequest:
    return EffectScheduleRequest(
        root_session_id=session_id,
        identity=EffectIdentity(
            authority_scope_hash="authority",
            tool_name="publish",
            operation_kind="create",
            target_hash="target",
            canonical_effect_hash="effect",
        ),
        request_hash="a" * 64,
        payload_artifact_ref=f"artifact://{reservation.artifact_id}",
        started_event=started,
    )


def _finalize(
    reservation: ArtifactReserveRequest,
    receipt: ArtifactObjectReceipt,
    event: SessionEvent,
) -> ArtifactFinalizeRequest:
    return ArtifactFinalizeRequest(
        artifact_id=reservation.artifact_id,
        session_id=reservation.session_id,
        expected_lifecycle_revision=1,
        idempotency_key=f"effect-payload-finalize-{reservation.intended_event_sequence}",
        event_binding=ArtifactEventBinding(
            session_id=reservation.session_id,
            event_id=event.event_id,
            sequence=event.sequence,
            artifact_uri=f"artifact://{reservation.artifact_id}",
        ),
        object_receipt=receipt,
        finalized_at=datetime.now(UTC),
    )


def _metadata(
    store: PostgresCloudArtifactPayloadStore,
    namespace: str,
    reservation: ArtifactReserveRequest,
) -> CloudArtifactPayloadRecord:
    metadata = store.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=namespace,
            artifact_id=reservation.artifact_id,
            session_id=reservation.session_id,
        )
    )
    assert metadata is not None
    return metadata


def _effect_status(dsn: str) -> str:
    with psycopg.connect(dsn) as connection:
        row = connection.execute("SELECT status FROM effect_outbox").fetchone()
    assert row is not None
    return str(row[0])


def _effect_count(dsn: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute("SELECT count(*) FROM effect_outbox").fetchone()
    assert row is not None
    return int(row[0])


def _metadata_count(dsn: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute("SELECT count(*) FROM artifact_payload_metadata").fetchone()
    assert row is not None
    return int(row[0])


def _result() -> ToolResult:
    return ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="created",
    )
