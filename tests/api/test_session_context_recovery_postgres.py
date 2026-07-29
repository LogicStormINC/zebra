from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextSourceEventRange,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.domain.leases import LeaseFence
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
    sqlite_control_plane_stores,
)
from zebra_agent_api import RouteAdapter, RouteRequest, create_app


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> Generator[str, None, None]:
    value = f"context-admin-{uuid4()}"
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


def test_http_recovery_uses_atomic_postgres_result(
    postgres_dsn: str,
    namespace: str,
    tmp_path: Path,
) -> None:
    session, workspace, historical, active = _two_capsules(postgres_dsn, namespace)
    projections = PostgresProjectionStore(postgres_dsn, deployment_namespace=namespace)
    projection_spy = Mock(wraps=projections)
    stores = replace(
        sqlite_control_plane_stores(tmp_path / "unused.sqlite"),
        events=PostgresEventStore(postgres_dsn, deployment_namespace=namespace),
        sessions=projection_spy,
        workspaces=PostgresWorkspaceProjectionStore(
            postgres_dsn, deployment_namespace=namespace
        ),
        context_lifecycle=PostgresContextLifecycleStore(
            postgres_dsn, deployment_namespace=namespace
        ),
    )
    response = RouteAdapter(
        create_app(
            tmp_path / "legacy.sqlite",
            stores=stores,
            administrative_context_namespace=namespace,
        )
    ).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session.session_id}/context/recover",
            body={"capsule_id": historical.capsule_id},
        )
    )

    assert response.status_code == 200
    assert set(response.body) == {"session_id", "status", "sequence", "capsule"}
    assert response.body["status"] == "recovered"
    capsule_body = response.body["capsule"]
    assert isinstance(capsule_body, dict)
    assert capsule_body["capsule_id"] == historical.capsule_id
    assert response.body["sequence"] == active.current_sequence + 1
    assert projection_spy.save_session.call_count == 0
    lifecycle = PostgresContextLifecycleStore(postgres_dsn, deployment_namespace=namespace)
    assert lifecycle.get_active_capsule(session.session_id).capsule == historical  # type: ignore[union-attr]
    stored_session = projections.get_session(session.session_id)
    stored_workspace = PostgresWorkspaceProjectionStore(
        postgres_dsn, deployment_namespace=namespace
    ).get_workspace(session.session_id)
    assert stored_session is not None and stored_workspace is not None
    assert stored_session.current_sequence == stored_workspace.current_sequence
    canonical = PostgresEventStore(
        postgres_dsn, deployment_namespace=namespace
    ).list_for_session(session.session_id)[-1]
    with psycopg.connect(postgres_dsn) as connection:
        pointer = connection.execute(
            "SELECT capsule_id, event_sequence, updated_at "
            "FROM active_context_projections "
            "WHERE deployment_namespace = %s AND session_id = %s",
            (namespace, session.session_id),
        ).fetchone()
    assert pointer is not None
    assert pointer[0] == historical.capsule_id
    assert pointer[1] == canonical.sequence
    assert pointer[2] == canonical.created_at


@pytest.mark.parametrize("projection_fault", ["missing", "changed", "stale"])
def test_administrative_recovery_rejects_workspace_drift_without_writes(
    postgres_dsn: str,
    namespace: str,
    projection_fault: str,
) -> None:
    session, workspace, historical, active = _two_capsules(postgres_dsn, namespace)
    with psycopg.connect(postgres_dsn) as connection:
        if projection_fault == "missing":
            connection.execute(
                "DELETE FROM workspace_projections "
                "WHERE deployment_namespace = %s AND session_id = %s",
                (namespace, session.session_id),
            )
        else:
            connection.execute(
                "UPDATE workspace_projections SET "
                + (
                    "current_sequence = current_sequence - 1 "
                    if projection_fault == "stale"
                    else "workspace_root = '/tmp/tampered' "
                )
                + "WHERE deployment_namespace = %s AND session_id = %s",
                (namespace, session.session_id),
            )
    store = PostgresContextLifecycleStore(postgres_dsn, deployment_namespace=namespace)
    provided_workspace = (
        PostgresWorkspaceProjectionStore(
            postgres_dsn, deployment_namespace=namespace
        ).get_workspace(session.session_id)
        if projection_fault == "stale"
        else workspace
    )
    assert provided_workspace is not None
    before = _event_count(postgres_dsn, namespace, session.session_id)

    with pytest.raises(
        PostgresContextLifecycleConflictError,
        match="administrative Context projections changed",
    ):
        store.commit_administrative_activation(
            authority=AdministrativeMutationCAS(
                deployment_namespace=namespace,
                session_id=session.session_id,
                expected_stream_revision=active.current_sequence,
            ),
            session=active,
            workspace=provided_workspace,
            capsule_id=historical.capsule_id,
            expected_active_capsule_id="current",
            event=_recovery_event(active, historical),
        )

    assert _event_count(postgres_dsn, namespace, session.session_id) == before
    stored_active = store.get_active_capsule(session.session_id)
    assert stored_active is not None and stored_active.capsule.capsule_id == "current"


def test_administrative_recovery_rejects_composition_namespace(
    postgres_dsn: str,
    namespace: str,
) -> None:
    session, workspace, historical, active = _two_capsules(postgres_dsn, namespace)
    store = PostgresContextLifecycleStore(postgres_dsn, deployment_namespace=namespace)
    before = _event_count(postgres_dsn, namespace, session.session_id)
    with pytest.raises(PostgresContextLifecycleConflictError, match="scope"):
        store.commit_administrative_activation(
            authority=AdministrativeMutationCAS(
                deployment_namespace=f"other-{namespace}",
                session_id=session.session_id,
                expected_stream_revision=active.current_sequence,
            ),
            session=active,
            workspace=workspace,
            capsule_id=historical.capsule_id,
            expected_active_capsule_id="current",
            event=_recovery_event(active, historical),
        )
    assert _event_count(postgres_dsn, namespace, session.session_id) == before


def _two_capsules(
    dsn: str, namespace: str
) -> tuple[Session, WorkspaceProjection, ContextCapsule, Session]:
    session_id = new_session_id()
    created_at = datetime(2026, 7, 29, tzinfo=UTC)
    created = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.USER,
        payload={"title": "Context"},
        created_at=created_at,
    )
    prepared = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.SYSTEM,
        payload={
            "title": "Context",
            "user_input": "Recover historical context.",
            "workspace_root": "/tmp/context",
        },
        created_at=created_at,
    )
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    events.append(created)
    projections = PostgresProjectionStore(dsn, deployment_namespace=namespace)
    projections.save_session(rebuild_session([created]))
    session = rebuild_session([created, prepared])
    workspace = rebuild_workspace([created, prepared])
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id, owner_instance_id="worker-a", ttl=timedelta(minutes=5)
    )
    PostgresWorkspaceProjectionStore(dsn, deployment_namespace=namespace).commit_worker_event(
        prepared,
        session,
        workspace,
        authority=WorkerMutationAuthority(
            deployment_namespace=namespace,
            session_id=session_id,
            lease_fence=lease.fence,
            expected_stream_revision=0,
        ),
    )
    store = PostgresContextLifecycleStore(dsn, deployment_namespace=namespace)
    historical = _capsule("historical")
    first = store.commit_worker_compaction(
        authority=_worker_authority(namespace, lease.fence, session),
        session=session,
        workspace=workspace,
        capsule=historical,
        validation_context=_validation(historical),
        expected_active_capsule_id=None,
        compaction_event=_compaction_event(session, historical),
    )
    current = _capsule("current")
    second = store.commit_worker_compaction(
        authority=_worker_authority(namespace, lease.fence, first.session),
        session=first.session,
        workspace=first.workspace,
        capsule=current,
        validation_context=_validation(current),
        expected_active_capsule_id=historical.capsule_id,
        compaction_event=_compaction_event(first.session, current),
    )
    return session, second.workspace, historical, second.session


def _worker_authority(
    namespace: str, fence: LeaseFence, session: Session
) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=session.session_id,
        lease_fence=fence,
        expected_stream_revision=session.current_sequence,
    )


def _capsule(capsule_id: str) -> ContextCapsule:
    return ContextCapsule(
        capsule_id=capsule_id,
        objective="Continue",
        immediate_next="Continue",
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=1),
        source_hash=("a" if capsule_id == "historical" else "b") * 64,
        confidence=1.0,
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )


def _validation(capsule: ContextCapsule) -> ContextCapsuleValidationContext:
    assert capsule.source_event_range is not None
    return ContextCapsuleValidationContext(
        expected_source_hash=capsule.source_hash,
        expected_source_event_range=capsule.source_event_range,
    )


def _compaction_event(session: Session, capsule: ContextCapsule) -> SessionEvent:
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


def _recovery_event(session: Session, capsule: ContextCapsule) -> SessionEvent:
    return _compaction_event(session, capsule).model_copy(
        update={
            "idempotency_key": f"context-recover:{capsule.capsule_id}",
            "created_at": datetime(2026, 7, 30, tzinfo=UTC),
        }
    )


def _event_count(dsn: str, namespace: str, session_id: SessionId) -> int:
    return len(
        PostgresEventStore(dsn, deployment_namespace=namespace).list_for_session(session_id)
    )
