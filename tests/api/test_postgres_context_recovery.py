from __future__ import annotations

import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
from agent_core.domain.leases import WorkerLease
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports import (
    AdministrativeMutationCAS,
    ContextLifecycleCommitResult,
    StoredContextCapsule,
    WorkerMutationAuthority,
)
from agent_storage import (
    ControlPlaneStores,
    PostgresContextLifecycleStore,
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    sqlite_control_plane_stores,
)
from psycopg import sql
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.responses import ApiResponse


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def namespace(postgres_dsn: str) -> Generator[str, None, None]:
    value = f"context-api-{uuid4()}"
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


def test_postgres_recovery_uses_administrative_cas_and_preserves_http_contract(
    postgres_dsn: str, namespace: str, tmp_path: Path
) -> None:
    session, workspace, first, second = _seed_capsules(postgres_dsn, namespace)
    stores = _stores(postgres_dsn, namespace, tmp_path)

    missing_namespace = RouteAdapter(
        create_app(tmp_path / "legacy.sqlite", stores=stores)
    ).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session.session_id}/context/recover",
            body={"capsule_id": first.capsule.capsule_id},
        )
    )
    assert missing_namespace.status_code == 503
    assert missing_namespace.body["status"] == "context_postgres_recovery_unavailable"

    response = RouteAdapter(
        create_app(
            tmp_path / "legacy.sqlite",
            stores=stores,
            context_administrative_namespace=namespace,
        )
    ).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session.session_id}/context/recover",
            body={"capsule_id": first.capsule.capsule_id},
        )
    )

    assert response.status_code == 200
    assert response.body == {
        "session_id": str(session.session_id),
        "status": "recovered",
        "sequence": second.session.current_sequence + 1,
        "capsule": first.capsule.model_dump(mode="json"),
    }
    assert stores.context_lifecycle.get_active_capsule(session.session_id) == first
    stored_session = stores.sessions.get_session(session.session_id)
    stored_workspace = stores.workspaces.get_workspace(session.session_id)
    assert stored_session is not None
    assert stored_workspace is not None
    assert stored_session.current_sequence == response.body["sequence"]
    assert stored_workspace.current_sequence == response.body["sequence"]
    assert len(stores.events.list_for_session(session.session_id)) == 7

    unsupported = RouteAdapter(
        create_app(
            tmp_path / "legacy.sqlite",
            stores=stores,
            context_administrative_namespace=namespace,
        )
    ).handle(
        RouteRequest(method="POST", path=f"/sessions/{session.session_id}/context/compact")
    )
    assert unsupported.status_code == 503
    assert unsupported.body["status"] == "context_manual_compaction_unavailable"


@pytest.mark.parametrize("race", ["revision", "pointer"])
def test_postgres_recovery_rejects_stale_revision_or_pointer_without_recovery_write(
    postgres_dsn: str, namespace: str, tmp_path: Path, race: str
) -> None:
    session, _, first, second = _seed_capsules(postgres_dsn, namespace)
    events = PostgresEventStore(postgres_dsn, deployment_namespace=namespace)
    store = _RacingContextStore(
        postgres_dsn,
        deployment_namespace=namespace,
        before_activation=(
            _append_racing_event(events, second.session)
            if race == "revision"
            else _replace_pointer(postgres_dsn, namespace, session.session_id, first)
        ),
    )
    stores = _stores(postgres_dsn, namespace, tmp_path, context_lifecycle=store)

    response = _recover(stores, namespace, tmp_path, session.session_id, first.capsule.capsule_id)

    assert response.status_code == 409
    assert response.body["status"] == "context_recovery_conflict"
    assert len(events.list_for_session(session.session_id)) == 7 if race == "revision" else 6
    assert stores.context_lifecycle.get_active_capsule(session.session_id) == (
        second.stored_capsule if race == "revision" else first
    )


def test_postgres_recovery_rejects_wrong_namespace_without_writes(
    postgres_dsn: str, namespace: str, tmp_path: Path
) -> None:
    session, _, first, second = _seed_capsules(postgres_dsn, namespace)
    stores = _stores(postgres_dsn, namespace, tmp_path)

    response = _recover(
        stores,
        f"{namespace}-wrong",
        tmp_path,
        session.session_id,
        first.capsule.capsule_id,
    )

    assert response.status_code == 409
    assert response.body["status"] == "context_recovery_conflict"
    assert len(stores.events.list_for_session(session.session_id)) == 6
    assert stores.context_lifecycle.get_active_capsule(session.session_id) == second.stored_capsule


@pytest.mark.parametrize(
    ("table", "status"),
    [
        ("active_context_projections", "context_pointer_missing"),
        ("workspace_projections", "context_workspace_missing"),
    ],
)
def test_postgres_recovery_fails_closed_when_required_projection_is_missing(
    postgres_dsn: str,
    namespace: str,
    tmp_path: Path,
    table: str,
    status: str,
) -> None:
    session, _, first, _ = _seed_capsules(postgres_dsn, namespace)
    stores = _stores(postgres_dsn, namespace, tmp_path)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            f"DELETE FROM {table} WHERE deployment_namespace = %s AND session_id = %s",
            (namespace, session.session_id),
        )

    response = _recover(stores, namespace, tmp_path, session.session_id, first.capsule.capsule_id)

    assert response.status_code == 409
    assert response.body["status"] == status
    assert len(stores.events.list_for_session(session.session_id)) == 6


def test_postgres_recovery_rolls_back_event_and_pointer_on_workspace_fault(
    postgres_dsn: str, namespace: str, tmp_path: Path
) -> None:
    session, _, first, second = _seed_capsules(postgres_dsn, namespace)
    stores = _stores(postgres_dsn, namespace, tmp_path)

    with _workspace_fault(postgres_dsn, namespace):
        with pytest.raises(psycopg.Error, match="context recovery projection fault"):
            _recover(stores, namespace, tmp_path, session.session_id, first.capsule.capsule_id)

    assert len(stores.events.list_for_session(session.session_id)) == 6
    assert stores.context_lifecycle.get_active_capsule(session.session_id) == second.stored_capsule


class _RacingContextStore(PostgresContextLifecycleStore):
    def __init__(
        self,
        dsn: str,
        before_activation: Callable[[], None],
        *,
        deployment_namespace: str,
    ) -> None:
        super().__init__(dsn, deployment_namespace=deployment_namespace)
        self._before_activation = before_activation

    def commit_administrative_activation(
        self,
        *,
        authority: AdministrativeMutationCAS,
        session: Session,
        workspace: WorkspaceProjection,
        capsule_id: str,
        expected_active_capsule_id: str | None,
        event: SessionEvent,
    ) -> ContextLifecycleCommitResult:
        self._before_activation()
        return super().commit_administrative_activation(
            authority=authority,
            session=session,
            workspace=workspace,
            capsule_id=capsule_id,
            expected_active_capsule_id=expected_active_capsule_id,
            event=event,
        )


def _seed_capsules(
    dsn: str, namespace: str
) -> tuple[Session, WorkspaceProjection, StoredContextCapsule, ContextLifecycleCommitResult]:
    session, workspace, lease = _prepared(dsn, namespace)
    store = PostgresContextLifecycleStore(dsn, deployment_namespace=namespace)
    first_capsule = _capsule("context-api-first")
    first = store.commit_worker_compaction(
        authority=_authority(namespace, lease, session.current_sequence),
        session=session,
        workspace=workspace,
        capsule=first_capsule,
        validation_context=_validation(first_capsule),
        expected_active_capsule_id=None,
        compaction_event=_compaction(session, first_capsule),
    )
    second_capsule = _capsule("context-api-second")
    second = store.commit_worker_compaction(
        authority=_authority(namespace, lease, first.session.current_sequence),
        session=first.session,
        workspace=first.workspace,
        capsule=second_capsule,
        validation_context=_validation(second_capsule),
        expected_active_capsule_id=first_capsule.capsule_id,
        compaction_event=_compaction(first.session, second_capsule),
    )
    return session, workspace, first.stored_capsule, second


def _stores(
    dsn: str,
    namespace: str,
    tmp_path: Path,
    *,
    context_lifecycle: PostgresContextLifecycleStore | None = None,
) -> ControlPlaneStores:
    local = sqlite_control_plane_stores(tmp_path / "unused.sqlite")
    return replace(
        local,
        events=PostgresEventStore(dsn, deployment_namespace=namespace),
        sessions=PostgresProjectionStore(dsn, deployment_namespace=namespace),
        workspaces=PostgresWorkspaceProjectionStore(dsn, deployment_namespace=namespace),
        context_lifecycle=context_lifecycle
        or PostgresContextLifecycleStore(dsn, deployment_namespace=namespace),
    )


def _recover(
    stores: ControlPlaneStores,
    namespace: str,
    tmp_path: Path,
    session_id: SessionId,
    capsule_id: str,
) -> ApiResponse:
    return RouteAdapter(
        create_app(
            tmp_path / "legacy.sqlite",
            stores=stores,
            context_administrative_namespace=namespace,
        )
    ).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/context/recover",
            body={"capsule_id": capsule_id},
        )
    )


def _append_racing_event(events: PostgresEventStore, session: Session) -> Callable[[], None]:
    def append() -> None:
        events.append(
            SessionEvent.create(
                session_id=session.session_id,
                sequence=session.current_sequence + 1,
                event_type=EventType.SESSION_TITLE_UPDATED,
                actor=EventActor.SYSTEM,
                payload={"title": "Context race"},
                created_at=datetime(2026, 7, 29, tzinfo=UTC),
            )
        )

    return append


def _replace_pointer(
    dsn: str,
    namespace: str,
    session_id: SessionId,
    stored: StoredContextCapsule,
) -> Callable[[], None]:
    def replace_pointer() -> None:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                """
                UPDATE active_context_projections
                SET capsule_id = %s, artifact_id = %s, source_hash = %s
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (
                    stored.capsule.capsule_id,
                    stored.artifact_id,
                    stored.capsule.source_hash,
                    namespace,
                    session_id,
                ),
            )

    return replace_pointer


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
def _workspace_fault(dsn: str, namespace: str) -> Generator[None, None, None]:
    function = sql.Identifier(f"context_recovery_fault_{uuid4().hex}")
    trigger = sql.Identifier(f"context_recovery_fault_trigger_{uuid4().hex}")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE FUNCTION {}() RETURNS trigger AS $$
                BEGIN
                    IF NEW.deployment_namespace = {} THEN
                        RAISE EXCEPTION 'context recovery projection fault';
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
