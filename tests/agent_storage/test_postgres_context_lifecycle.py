from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.events import ContextCapsuleCreatedPayload
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextSourceEventRange,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports import AdministrativeMutationCAS, WorkerMutationAuthority
from agent_storage import (
    PostgresContextLifecycleConflictError,
    PostgresContextLifecycleStore,
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
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
def namespace(postgres_dsn: str) -> Generator[str, None, None]:
    value = f"context-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=value)
    yield value
    with psycopg.connect(postgres_dsn) as connection:
        for table in (
            "active_context_projections",
            "context_capsule_artifacts",
            "workspace_projections",
            "session_events",
            "session_projections",
            "session_streams",
            "worker_leases",
            "control_plane_epochs",
        ):
            connection.execute(f"DELETE FROM {table} WHERE deployment_namespace = %s", (value,))


def test_worker_context_commit_is_atomic_and_idempotent(postgres_dsn: str, namespace: str) -> None:
    session, workspace, lease = _prepared(postgres_dsn, namespace)
    capsule = _capsule("capsule-a")
    event = _compaction(session, capsule)
    store = PostgresContextLifecycleStore(postgres_dsn, deployment_namespace=namespace)
    authority = _authority(namespace, lease, session.current_sequence)

    committed = store.commit_worker_compaction(
        authority=authority,
        session=session,
        workspace=workspace,
        capsule=capsule,
        validation_context=_validation(capsule),
        expected_active_capsule_id=None,
        compaction_event=event,
    )

    assert committed.compaction_event.sequence == session.current_sequence + 1
    assert committed.stored_capsule.event.sequence == session.current_sequence + 2
    assert committed.session.current_sequence == committed.stored_capsule.event.sequence
    assert committed.workspace.current_sequence == committed.stored_capsule.event.sequence
    assert store.get_active_capsule(session.session_id) == committed.stored_capsule

    retried = store.commit_worker_compaction(
        authority=authority,
        session=session,
        workspace=workspace,
        capsule=capsule,
        validation_context=_validation(capsule),
        expected_active_capsule_id=None,
        compaction_event=event.model_copy(update={"event_id": uuid4()}),
    )
    assert retried == committed
    assert (
        len(
            PostgresEventStore(postgres_dsn, deployment_namespace=namespace).list_for_session(
                session.session_id
            )
        )
        == 4
    )


def test_worker_context_uses_existing_canonical_capsule_event(
    postgres_dsn: str, namespace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, workspace, lease = _prepared(postgres_dsn, namespace)
    capsule = _capsule("capsule-canonical")
    assert capsule.source_event_range is not None
    compaction = _compaction(session, capsule)
    canonical_artifact_id = uuid4()
    canonical_capsule = SessionEvent.create(
        session_id=session.session_id,
        sequence=compaction.sequence + 1,
        event_type=EventType.CONTEXT_CAPSULE_CREATED,
        actor=EventActor.SYSTEM,
        payload=ContextCapsuleCreatedPayload(
            capsule_id=capsule.capsule_id,
            artifact_id=str(canonical_artifact_id),
            schema_version=capsule.version,
            source_hash=capsule.source_hash,
            source_event_range=capsule.source_event_range,
            previous_capsule_id=None,
        ).model_dump(mode="json"),
        idempotency_key=f"context-capsule:{capsule.capsule_id}",
        created_at=compaction.created_at,
    )
    monkeypatch.setattr(
        "agent_storage.postgres.context_lifecycle.new_artifact_id",
        lambda: canonical_artifact_id,
    )
    events = PostgresEventStore(postgres_dsn, deployment_namespace=namespace)
    events.append(compaction)
    events.append(canonical_capsule)

    result = PostgresContextLifecycleStore(
        postgres_dsn, deployment_namespace=namespace
    ).commit_worker_compaction(
        authority=_authority(namespace, lease, session.current_sequence),
        session=session,
        workspace=workspace,
        capsule=capsule,
        validation_context=_validation(capsule),
        expected_active_capsule_id=None,
        compaction_event=compaction.model_copy(update={"event_id": uuid4()}),
    )

    assert result.stored_capsule.event.event_id == canonical_capsule.event_id
    assert result.stored_capsule.artifact_id == canonical_artifact_id
    assert result.session.current_sequence == canonical_capsule.sequence
    assert result.workspace.current_sequence == canonical_capsule.sequence


def test_context_schema_rejects_cross_session_event_and_pointer_artifact(
    postgres_dsn: str, namespace: str
) -> None:
    session, workspace, lease = _prepared(postgres_dsn, namespace)
    capsule = _capsule("capsule-fk")
    committed = PostgresContextLifecycleStore(
        postgres_dsn, deployment_namespace=namespace
    ).commit_worker_compaction(
        authority=_authority(namespace, lease, session.current_sequence),
        session=session,
        workspace=workspace,
        capsule=capsule,
        validation_context=_validation(capsule),
        expected_active_capsule_id=None,
        compaction_event=_compaction(session, capsule),
    )
    other_session_id = new_session_id()
    other_event = SessionEvent.create(
        session_id=other_session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.USER,
        payload={"title": "Other"},
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )
    PostgresEventStore(postgres_dsn, deployment_namespace=namespace).append(other_event)

    with psycopg.connect(postgres_dsn) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                """
                INSERT INTO context_capsule_artifacts (
                    deployment_namespace, capsule_id, artifact_id, session_id, payload,
                    payload_sha256, source_hash, compaction_event_id, capsule_event_id,
                    created_at
                ) VALUES (%s, %s, %s, %s, '{}'::jsonb, %s, %s, %s, %s, %s)
                """,
                (
                    namespace,
                    "capsule-cross-session-event",
                    uuid4(),
                    session.session_id,
                    "b" * 64,
                    "c" * 64,
                    other_event.event_id,
                    other_event.event_id,
                    datetime(2026, 7, 29, tzinfo=UTC),
                ),
            )

    with psycopg.connect(postgres_dsn) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                """
                INSERT INTO active_context_projections (
                    deployment_namespace, session_id, capsule_id, artifact_id,
                    source_hash, event_sequence, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    namespace,
                    other_session_id,
                    capsule.capsule_id,
                    committed.stored_capsule.artifact_id,
                    capsule.source_hash,
                    0,
                    datetime(2026, 7, 29, tzinfo=UTC),
                ),
            )


def test_worker_context_rejects_stale_fence_without_writes(
    postgres_dsn: str, namespace: str
) -> None:
    session, workspace, lease = _prepared(postgres_dsn, namespace)
    capsule = _capsule("capsule-stale")
    with pytest.raises(LeaseLostError):
        PostgresContextLifecycleStore(
            postgres_dsn, deployment_namespace=namespace
        ).commit_worker_compaction(
            authority=_authority(namespace, lease, session.current_sequence).model_copy(
                update={
                    "lease_fence": lease.fence.model_copy(
                        update={"fencing_token": lease.fence.fencing_token + 1}
                    )
                }
            ),
            session=session,
            workspace=workspace,
            capsule=capsule,
            validation_context=_validation(capsule),
            expected_active_capsule_id=None,
            compaction_event=_compaction(session, capsule),
        )
    assert (
        len(
            PostgresEventStore(postgres_dsn, deployment_namespace=namespace).list_for_session(
                session.session_id
            )
        )
        == 2
    )


def test_worker_context_rejects_stale_pointer_without_new_capsule(
    postgres_dsn: str, namespace: str
) -> None:
    session, workspace, lease = _prepared(postgres_dsn, namespace)
    store = PostgresContextLifecycleStore(postgres_dsn, deployment_namespace=namespace)
    first = _capsule("capsule-first")
    result = store.commit_worker_compaction(
        authority=_authority(namespace, lease, session.current_sequence),
        session=session,
        workspace=workspace,
        capsule=first,
        validation_context=_validation(first),
        expected_active_capsule_id=None,
        compaction_event=_compaction(session, first),
    )
    second = _capsule("capsule-second")
    with pytest.raises(PostgresContextLifecycleConflictError):
        store.commit_worker_compaction(
            authority=_authority(namespace, lease, result.session.current_sequence),
            session=result.session,
            workspace=result.workspace,
            capsule=second,
            validation_context=_validation(second),
            expected_active_capsule_id=None,
            compaction_event=_compaction(result.session, second),
        )
    assert store.get_capsule(second.capsule_id) is None


def test_administrative_context_cas_advances_primary_projections(
    postgres_dsn: str,
    namespace: str,
) -> None:
    session, workspace, lease = _prepared(postgres_dsn, namespace)
    store = PostgresContextLifecycleStore(postgres_dsn, deployment_namespace=namespace)
    capsule = _capsule("capsule-admin")
    committed = store.commit_worker_compaction(
        authority=_authority(namespace, lease, session.current_sequence),
        session=session,
        workspace=workspace,
        capsule=capsule,
        validation_context=_validation(capsule),
        expected_active_capsule_id=None,
        compaction_event=_compaction(session, capsule),
    )
    event = _compaction(committed.session, capsule).model_copy(
        update={"idempotency_key": f"context-admin:{capsule.capsule_id}"}
    )
    result = store.commit_administrative_activation(
        authority=AdministrativeMutationCAS(
            deployment_namespace=namespace,
            session_id=session.session_id,
            expected_stream_revision=committed.session.current_sequence,
        ),
        session=committed.session,
        workspace=committed.workspace,
        capsule_id=capsule.capsule_id,
        expected_active_capsule_id=capsule.capsule_id,
        event=event,
    )
    assert result.compaction_event.sequence == committed.stored_capsule.event.sequence + 1
    assert result.session.current_sequence == result.workspace.current_sequence


def test_administrative_context_missing_pointer_rolls_back_event(
    postgres_dsn: str, namespace: str
) -> None:
    session, workspace, lease = _prepared(postgres_dsn, namespace)
    store = PostgresContextLifecycleStore(postgres_dsn, deployment_namespace=namespace)
    capsule = _capsule("capsule-admin-missing")
    committed = store.commit_worker_compaction(
        authority=_authority(namespace, lease, session.current_sequence),
        session=session,
        workspace=workspace,
        capsule=capsule,
        validation_context=_validation(capsule),
        expected_active_capsule_id=None,
        compaction_event=_compaction(session, capsule),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "DELETE FROM active_context_projections "
            "WHERE deployment_namespace = %s AND session_id = %s",
            (namespace, session.session_id),
        )

    with pytest.raises(PostgresContextLifecycleConflictError):
        store.commit_administrative_activation(
            authority=AdministrativeMutationCAS(
                deployment_namespace=namespace,
                session_id=session.session_id,
                expected_stream_revision=committed.session.current_sequence,
            ),
            session=committed.session,
            workspace=committed.workspace,
            capsule_id=capsule.capsule_id,
            expected_active_capsule_id=capsule.capsule_id,
            event=_compaction(committed.session, capsule).model_copy(
                update={"idempotency_key": "context-admin-missing"}
            ),
        )
    assert store.get_active_capsule(session.session_id) is None
    assert len(
        PostgresEventStore(postgres_dsn, deployment_namespace=namespace).list_for_session(
            session.session_id
        )
    ) == 4


def test_worker_context_rolls_back_capsule_and_events_on_projection_fault(
    postgres_dsn: str,
    namespace: str,
) -> None:
    session, workspace, lease = _prepared(postgres_dsn, namespace)
    capsule = _capsule("capsule-rollback")
    store = PostgresContextLifecycleStore(postgres_dsn, deployment_namespace=namespace)
    with _workspace_fault(postgres_dsn, namespace):
        with pytest.raises(psycopg.Error, match="context projection fault"):
            store.commit_worker_compaction(
                authority=_authority(namespace, lease, session.current_sequence),
                session=session,
                workspace=workspace,
                capsule=capsule,
                validation_context=_validation(capsule),
                expected_active_capsule_id=None,
                compaction_event=_compaction(session, capsule),
            )
    assert store.get_capsule(capsule.capsule_id) is None
    assert store.get_active_capsule(session.session_id) is None
    assert (
        len(
            PostgresEventStore(postgres_dsn, deployment_namespace=namespace).list_for_session(
                session.session_id
            )
        )
        == 2
    )


def _prepared(dsn: str, namespace: str) -> tuple[Session, WorkspaceProjection, WorkerLease]:
    session_id = new_session_id()
    now = datetime(2026, 7, 29, tzinfo=UTC)
    created = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.USER,
        payload={"title": "Context"},
        created_at=now,
    )
    prepared = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.SYSTEM,
        payload={
            "title": "Context",
            "user_input": "Continue context lifecycle validation.",
            "workspace_root": "/tmp/context",
        },
        created_at=now,
    )
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    events.append(created)
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(
        rebuild_session([created])
    )
    session = rebuild_session([created, prepared])
    workspace = rebuild_workspace([created, prepared])
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id, owner_instance_id="worker-a", ttl=timedelta(minutes=5)
    )
    PostgresWorkspaceProjectionStore(dsn, deployment_namespace=namespace).commit_worker_event(
        prepared, session, workspace, authority=_authority(namespace, lease, 0)
    )
    return session, workspace, lease


def _authority(namespace: str, lease: WorkerLease, revision: int) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=lease.session_id,
        lease_fence=lease.fence,
        expected_stream_revision=revision,
    )


def _capsule(capsule_id: str) -> ContextCapsule:
    return ContextCapsule(
        capsule_id=capsule_id,
        objective="Continue",
        immediate_next="Continue",
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=1),
        source_hash="a" * 64,
        confidence=1.0,
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )


def _validation(capsule: ContextCapsule) -> ContextCapsuleValidationContext:
    assert capsule.source_event_range is not None
    return ContextCapsuleValidationContext(
        expected_source_hash=capsule.source_hash,
        expected_source_event_range=capsule.source_event_range,
    )


def _compaction(session: Session, capsule: ContextCapsule) -> SessionEvent:
    return SessionEvent.create(
        session_id=session.session_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.CONTEXT_COMPACTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "before_tokens": 10,
            "after_tokens": 5,
            "removed_message_count": 1,
            "retained_message_count": 1,
            "within_budget": True,
            "provenance": "test",
            "capsule": capsule.model_dump(mode="json"),
        },
        idempotency_key=f"context-compaction:{capsule.capsule_id}",
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )


@contextmanager
def _workspace_fault(dsn: str, namespace: str) -> Iterator[None]:
    function = sql.Identifier(f"context_fault_{uuid4().hex}")
    trigger = sql.Identifier(f"context_fault_trigger_{uuid4().hex}")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE FUNCTION {}() RETURNS trigger AS $$
                BEGIN
                    IF NEW.deployment_namespace = {} THEN
                        RAISE EXCEPTION 'context projection fault';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            ).format(function, sql.Literal(namespace))
        )
        connection.execute(
            sql.SQL(
                "CREATE TRIGGER {} BEFORE UPDATE ON workspace_projections "
                "FOR EACH ROW EXECUTE FUNCTION {}()"
            ).format(trigger, function)
        )
    try:
        yield
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("DROP TRIGGER IF EXISTS {} ON workspace_projections").format(trigger)
            )
            connection.execute(sql.SQL("DROP FUNCTION IF EXISTS {}()").format(function))
