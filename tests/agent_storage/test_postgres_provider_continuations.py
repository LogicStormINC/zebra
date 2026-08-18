from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence, LeaseLostError, WorkerLease
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports import AdministrativeMutationCAS, WorkerMutationAuthority
from agent_storage import (
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresProviderContinuationConflictError,
    PostgresProviderContinuationStore,
    PostgresWorkspaceProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from psycopg import sql


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def provider_namespace(postgres_dsn: str) -> Generator[str]:
    namespace = f"provider-continuation-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_commit_binds_payload_event_and_projections_atomically_and_replays(
    postgres_dsn: str,
    provider_namespace: str,
) -> None:
    seeded = _seed_session(postgres_dsn, provider_namespace)
    reference = _reference("ref-atomic")
    payload = b"provider-native-bytes"
    event = _selection_event(
        seeded.session.session_id,
        seeded.session.current_sequence + 1,
        reference,
        continuation_id="continuation-atomic",
        payload=payload,
        idempotency_key="selection-atomic",
    )
    store = _store(postgres_dsn, provider_namespace)
    authority = _authority(provider_namespace, seeded.lease, seeded.session.current_sequence)

    committed = store.commit_worker_selection(
        scope=seeded.scope,
        authority=authority,
        continuation_id="continuation-atomic",
        session=apply_session_event(seeded.session, event),
        workspace=apply_workspace_event(seeded.workspace, event),
        reference=reference,
        opaque_payload=payload,
        maximum_ttl_seconds=600,
        selection_event=event,
    )

    assert committed.event.sequence == 3
    assert committed.artifact.selection_event_id == committed.event.event_id
    assert committed.session.current_sequence == 3
    assert committed.workspace.current_sequence == 3
    loaded = store.load_compatible(
        "continuation-atomic",
        scope=seeded.scope,
        session_id=seeded.session.session_id,
        provider=reference.provider,
        model_name=reference.model_name,
        capability_version=reference.capability_version,
        as_of=datetime(2026, 1, 1, 9, 2, tzinfo=UTC),
    )
    assert loaded is not None
    assert loaded.opaque_payload == payload

    retry = event.model_copy(update={"event_id": uuid4(), "created_at": _at(10)})
    replayed = store.commit_worker_selection(
        scope=seeded.scope,
        authority=authority,
        continuation_id="continuation-atomic",
        session=apply_session_event(seeded.session, retry),
        workspace=apply_workspace_event(seeded.workspace, retry),
        reference=reference,
        opaque_payload=payload,
        maximum_ttl_seconds=600,
        selection_event=retry,
    )
    assert replayed.event == committed.event
    assert replayed.artifact == committed.artifact
    assert _count(postgres_dsn, provider_namespace, "provider_continuation_artifacts") == 1
    assert _count(postgres_dsn, provider_namespace, "session_events") == 4


def test_stale_fence_and_projection_conflict_leave_no_dangling_continuation(
    postgres_dsn: str,
    provider_namespace: str,
) -> None:
    seeded = _seed_session(postgres_dsn, provider_namespace)
    store = _store(postgres_dsn, provider_namespace)
    reference = _reference("ref-rollback")
    payload = b"rollback-bytes"
    event = _selection_event(
        seeded.session.session_id,
        3,
        reference,
        continuation_id="continuation-rollback",
        payload=payload,
        idempotency_key="selection-rollback",
    )
    next_session = apply_session_event(seeded.session, event)
    next_workspace = apply_workspace_event(seeded.workspace, event)

    with pytest.raises(LeaseLostError):
        store.commit_worker_selection(
            scope=seeded.scope,
            authority=_authority(
                provider_namespace,
                seeded.lease,
                seeded.session.current_sequence,
                fence=seeded.lease.fence.model_copy(
                    update={"fencing_token": seeded.lease.fence.fencing_token + 1}
                ),
            ),
            continuation_id="continuation-rollback",
            session=next_session,
            workspace=next_workspace,
            reference=reference,
            opaque_payload=payload,
            maximum_ttl_seconds=600,
            selection_event=event,
        )

    with pytest.raises(PostgresProviderContinuationConflictError, match="not derived"):
        store.commit_worker_selection(
            scope=seeded.scope,
            authority=_authority(provider_namespace, seeded.lease, seeded.session.current_sequence),
            continuation_id="continuation-rollback",
            session=next_session,
            workspace=next_workspace.model_copy(update={"workspace_root": "/tmp/tampered"}),
            reference=reference,
            opaque_payload=payload,
            maximum_ttl_seconds=600,
            selection_event=event,
        )

    assert _count(postgres_dsn, provider_namespace, "provider_continuation_artifacts") == 0
    assert _count(postgres_dsn, provider_namespace, "session_events") == 3
    assert _count(postgres_dsn, provider_namespace, "workspace_projections") == 1


def test_scope_isolation_ttl_sha_and_worker_soft_delete(
    postgres_dsn: str,
    provider_namespace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = _seed_session(postgres_dsn, provider_namespace)
    reference = _reference("ref-lifecycle")
    payload = b"lifecycle-bytes"
    event = _selection_event(
        seeded.session.session_id,
        3,
        reference,
        continuation_id="continuation-lifecycle",
        payload=payload,
        idempotency_key="selection-lifecycle",
    )
    store = _store(postgres_dsn, provider_namespace)
    authority = _authority(provider_namespace, seeded.lease, seeded.session.current_sequence)
    committed = store.commit_worker_selection(
        scope=seeded.scope,
        authority=authority,
        continuation_id="continuation-lifecycle",
        session=apply_session_event(seeded.session, event),
        workspace=apply_workspace_event(seeded.workspace, event),
        reference=reference,
        opaque_payload=payload,
        maximum_ttl_seconds=600,
        selection_event=event,
    )

    other_scope = OpaqueAuthorityScope(
        authority_issuer="other-issuer",
        namespace_id=seeded.scope.namespace_id,
    )
    assert (
        store.load_compatible(
            "continuation-lifecycle",
            scope=other_scope,
            session_id=seeded.session.session_id,
            provider=reference.provider,
            model_name=reference.model_name,
            capability_version=reference.capability_version,
        )
        is None
    )
    assert (
        store.load_compatible(
            "continuation-lifecycle",
            scope=seeded.scope,
            session_id=seeded.session.session_id,
            provider=reference.provider,
            model_name=reference.model_name,
            capability_version=reference.capability_version,
            as_of=reference.expires_at,
        )
        is None
    )

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE provider_continuation_artifacts
            SET opaque_payload = %s
            WHERE deployment_namespace = %s AND continuation_id = %s
            """,
            (b"tampered", provider_namespace, "continuation-lifecycle"),
        )
    with pytest.raises(ValueError, match="integrity"):
        store.load_compatible(
            "continuation-lifecycle",
            scope=seeded.scope,
            session_id=seeded.session_id,
            provider=reference.provider,
            model_name=reference.model_name,
            capability_version=reference.capability_version,
            as_of=_at(2),
        )

    with pytest.raises(PostgresProviderContinuationConflictError, match="does not allow"):
        store.delete_for_worker(
            "continuation-lifecycle",
            scope=seeded.scope.model_copy(update={"allowed_session_ids": ()}),
            authority=authority,
            idempotency_key="delete-denied",
        )

    with pytest.raises(PostgresProviderContinuationConflictError, match="stream revision"):
        store.delete_for_worker(
            "continuation-lifecycle",
            scope=seeded.scope,
            authority=authority,
            idempotency_key="delete-stale-revision",
        )
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT lifecycle_revision, deleted_at
            FROM provider_continuation_artifacts
            WHERE deployment_namespace = %s AND continuation_id = %s
            """,
            (provider_namespace, "continuation-lifecycle"),
        ).fetchone()
    assert row == (0, None)

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            INSERT INTO provider_continuation_mutations (
                deployment_namespace, continuation_id, operation_kind,
                idempotency_key, request_hash, resulting_revision
            ) VALUES (%s, %s, 'delete', %s, %s, 0)
            """,
            (
                provider_namespace,
                "continuation-lifecycle",
                "delete-rollback",
                "0" * 64,
            ),
        )
    monkeypatch.setattr(
        "agent_storage.postgres.provider_continuations.find_mutation",
        lambda *_args: None,
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.delete_for_worker(
            "continuation-lifecycle",
            scope=seeded.scope,
            authority=_authority(
                provider_namespace,
                seeded.lease,
                committed.event.sequence,
            ),
            idempotency_key="delete-rollback",
            deleted_at=_at(4),
        )
    monkeypatch.undo()
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT lifecycle_revision, deleted_at
            FROM provider_continuation_artifacts
            WHERE deployment_namespace = %s AND continuation_id = %s
            """,
            (provider_namespace, "continuation-lifecycle"),
        ).fetchone()
    assert row == (0, None)

    delete_authority = _authority(
        provider_namespace,
        seeded.lease,
        committed.event.sequence,
    )

    deleted = store.delete_for_worker(
        "continuation-lifecycle",
        scope=seeded.scope,
        authority=delete_authority,
        idempotency_key="delete-lifecycle",
        deleted_at=_at(4),
    )
    assert deleted is not None
    assert deleted.deleted_at == _at(4)
    replayed = store.delete_for_worker(
        "continuation-lifecycle",
        scope=seeded.scope,
        authority=delete_authority,
        idempotency_key="delete-lifecycle",
        deleted_at=_at(5),
    )
    assert replayed == deleted
    assert (
        store.load_compatible(
            "continuation-lifecycle",
            scope=seeded.scope,
            session_id=seeded.session_id,
            provider=reference.provider,
            model_name=reference.model_name,
            capability_version=reference.capability_version,
            as_of=_at(2),
        )
        is None
    )


def test_scoped_sweep_is_audited_and_idempotent(
    postgres_dsn: str,
    provider_namespace: str,
) -> None:
    seeded = _seed_session(postgres_dsn, provider_namespace)
    reference = _reference("ref-sweep", expires_at=_at(2))
    payload = b"expired-bytes"
    event = _selection_event(
        seeded.session.session_id,
        3,
        reference,
        continuation_id="continuation-expired",
        payload=payload,
        idempotency_key="selection-expired",
    )
    store = _store(postgres_dsn, provider_namespace)
    authority = _authority(provider_namespace, seeded.lease, seeded.session.current_sequence)
    store.commit_worker_selection(
        scope=seeded.scope,
        authority=authority,
        continuation_id="continuation-expired",
        session=apply_session_event(seeded.session, event),
        workspace=apply_workspace_event(seeded.workspace, event),
        reference=reference,
        opaque_payload=payload,
        maximum_ttl_seconds=600,
        selection_event=event,
    )
    management = AdministrativeMutationCAS(
        deployment_namespace=provider_namespace,
        session_id=seeded.session.session_id,
        expected_stream_revision=3,
    )
    operation_id = uuid4()
    receipt = store.sweep_expired(
        scope=seeded.scope.model_copy(update={"allowed_session_ids": None}),
        authority=management,
        operation_id=operation_id,
        operator_id="retention-worker",
        reason="provider continuation TTL elapsed",
        as_of=None,
    )

    assert receipt.expired_continuation_ids == ("continuation-expired",)
    replay = store.sweep_expired(
        scope=seeded.scope.model_copy(update={"allowed_session_ids": None}),
        authority=management,
        operation_id=operation_id,
        operator_id="retention-worker",
        reason="provider continuation TTL elapsed",
        as_of=None,
    )
    assert replay == receipt
    assert _count(postgres_dsn, provider_namespace, "provider_continuation_management_audit") == 1
    assert (
        store.load_compatible(
            "continuation-expired",
            scope=seeded.scope,
            session_id=seeded.session_id,
            provider=reference.provider,
            model_name=reference.model_name,
            capability_version=reference.capability_version,
            as_of=_at(3),
        )
        is None
    )


class _SeededSession:
    def __init__(
        self,
        session: Session,
        workspace: WorkspaceProjection,
        lease: WorkerLease,
        scope: OpaqueAuthorityScope,
    ) -> None:
        self.session = session
        self.session_id = session.session_id
        self.workspace = workspace
        self.lease = lease
        self.scope = scope


def _seed_session(dsn: str, namespace: str) -> _SeededSession:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Provider continuation",
            user_input="continue",
            workspace_root=Path("/tmp/provider-continuation"),
            created_at=_at(1),
        )
    )
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    for event in bootstrap.events:
        events.append(event)
    workspace = rebuild_workspace(list(bootstrap.events))
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(bootstrap.session)
    PostgresWorkspaceProjectionStore(dsn, deployment_namespace=namespace).save_workspace(workspace)
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        bootstrap.session.session_id,
        owner_instance_id="provider-worker",
        ttl=timedelta(minutes=5),
    )
    scope = OpaqueAuthorityScope(
        authority_issuer="issuer",
        namespace_id="business-scope",
        allowed_session_ids=(str(bootstrap.session.session_id),),
    )
    return _SeededSession(bootstrap.session, workspace, lease, scope)


def _store(dsn: str, namespace: str) -> PostgresProviderContinuationStore:
    return PostgresProviderContinuationStore(
        dsn,
        deployment_namespace=namespace,
        scope=OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="business-scope",
        ),
    )


def _authority(
    namespace: str,
    lease: WorkerLease,
    expected_revision: int,
    *,
    fence: LeaseFence | None = None,
) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=lease.session_id,
        lease_fence=fence or lease.fence,
        expected_stream_revision=expected_revision,
    )


def _reference(
    reference_id: str,
    *,
    expires_at: datetime | None = None,
) -> ProviderContinuationRef:
    created_at = _at(1)
    return ProviderContinuationRef(
        reference_id=reference_id,
        provider="provider-a",
        model_name="model-a",
        capability_version="1",
        source_hash="source-hash",
        created_at=created_at,
        expires_at=expires_at or created_at + timedelta(minutes=5),
    )


def _selection_event(
    session_id: SessionId,
    sequence: int,
    reference: ProviderContinuationRef,
    *,
    continuation_id: str,
    payload: bytes,
    idempotency_key: str,
) -> SessionEvent:
    from hashlib import sha256

    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.CONTEXT_CONTINUATION_SELECTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "mode": "provider_native",
            "reason": "provider reference accepted",
            "reference_id": reference.reference_id,
            "provider": reference.provider,
            "model_name": reference.model_name,
            "capability_version": reference.capability_version,
            "source_hash": reference.source_hash,
            "artifact_id": continuation_id,
            "authority_issuer": "issuer",
            "namespace_id": "business-scope",
            "payload_sha256": sha256(payload).hexdigest(),
        },
        idempotency_key=idempotency_key,
        created_at=_at(2),
    )


def _at(minute: int) -> datetime:
    return datetime(2026, 1, 1, 9, minute, tzinfo=UTC)


def _count(dsn: str, namespace: str, table: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            sql.SQL("SELECT count(*) FROM {} WHERE deployment_namespace = %s").format(
                sql.Identifier(table)
            ),
            (namespace,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        for table in (
            "provider_continuation_mutations",
            "provider_continuation_management_audit",
            "provider_continuation_artifacts",
            "workspace_projections",
            "effect_outbox",
            "session_events",
            "session_projections",
            "session_streams",
            "worker_leases",
            "control_plane_epochs",
        ):
            connection.execute(
                sql.SQL("DELETE FROM {} WHERE deployment_namespace = %s").format(
                    sql.Identifier(table)
                ),
                (namespace,),
            )
