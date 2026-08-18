from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.domain.leases import LeaseFence, LeaseLostError, WorkerLease
from agent_core.ports import WorkerMutationAuthority
from agent_storage import (
    PostgresEventStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionConflictError,
    PostgresWorkspaceProjectionStore,
    SQLiteArtifactPayloadStore,
    SQLiteModelCallStore,
    SQLiteToolRunStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from psycopg import sql
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def workspace_namespace(postgres_dsn: str) -> Generator[str]:
    namespace = f"workspace-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_worker_commit_atomically_persists_event_and_primary_projections(
    postgres_dsn: str,
    workspace_namespace: str,
) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    session = rebuild_session([created, prepared])
    workspace = rebuild_workspace([created, prepared])
    store = _store(postgres_dsn, workspace_namespace)

    stored = store.commit_worker_event(
        prepared,
        session,
        workspace,
        authority=_authority(workspace_namespace, lease, expected_revision=0),
    )

    assert stored.event == prepared
    assert stored.session == session
    assert stored.workspace == workspace
    assert store.get_workspace(session_id) == workspace
    assert _events_store(postgres_dsn, workspace_namespace).list_for_session(session_id) == [
        created,
        prepared,
    ]
    assert _sessions(postgres_dsn, workspace_namespace).get_session(session_id) == session

    retried = store.commit_worker_event(
        prepared,
        session,
        workspace,
        authority=_authority(workspace_namespace, lease, expected_revision=0),
    )
    assert retried.workspace == workspace


def test_worker_commit_returns_canonical_projections_after_lost_ack_retry(
    postgres_dsn: str,
    workspace_namespace: str,
) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    canonical_session = rebuild_session([created, prepared])
    canonical_workspace = rebuild_workspace([created, prepared])
    store = _store(postgres_dsn, workspace_namespace)
    authority = _authority(workspace_namespace, lease, expected_revision=0)
    store.commit_worker_event(
        prepared,
        canonical_session,
        canonical_workspace,
        authority=authority,
    )
    retry = prepared.model_copy(
        update={
            "event_id": uuid4(),
            "sequence": prepared.sequence + 7,
            "created_at": prepared.created_at + timedelta(seconds=30),
        }
    )

    committed = store.commit_worker_event(
        retry,
        canonical_session,
        canonical_workspace,
        authority=authority,
    )

    assert committed.event == prepared
    assert committed.session == canonical_session
    assert committed.workspace == canonical_workspace
    assert _events_store(postgres_dsn, workspace_namespace).list_for_session(session_id) == [
        created,
        prepared,
    ]


def test_worker_projects_effect_persisted_event_without_second_append(
    postgres_dsn: str,
    workspace_namespace: str,
) -> None:
    session_id = new_session_id()
    created, persisted = _events(session_id)
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    event_store = _events_store(postgres_dsn, workspace_namespace)
    event_store.append(persisted)
    session = rebuild_session([created, persisted])
    workspace = rebuild_workspace([created, persisted])
    store = _store(postgres_dsn, workspace_namespace)
    authority = _authority(workspace_namespace, lease, expected_revision=created.sequence)

    committed = store.project_persisted_worker_event(
        persisted,
        session,
        workspace,
        authority=authority,
    )

    assert committed.event == persisted
    assert committed.session == session
    assert committed.workspace == workspace
    assert _events_store(postgres_dsn, workspace_namespace).list_for_session(session_id) == [
        created,
        persisted,
    ]
    assert _sessions(postgres_dsn, workspace_namespace).get_session(session_id) == session
    assert store.get_workspace(session_id) == workspace
    assert (
        store.project_persisted_worker_event(
            persisted,
            session,
            workspace,
            authority=authority,
        )
        == committed
    )


@pytest.mark.parametrize("tampered_projection", ["session", "workspace"])
def test_worker_commit_rejects_projection_content_not_derived_from_event(
    postgres_dsn: str,
    workspace_namespace: str,
    tampered_projection: str,
) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    session = rebuild_session([created, prepared])
    workspace = rebuild_workspace([created, prepared])
    if tampered_projection == "session":
        session = session.model_copy(update={"title": "tampered"})
    else:
        workspace = workspace.model_copy(update={"workspace_root": "/tmp/tampered"})

    with pytest.raises(PostgresWorkspaceProjectionConflictError, match="not derived"):
        _store(postgres_dsn, workspace_namespace).commit_worker_event(
            prepared,
            session,
            workspace,
            authority=_authority(workspace_namespace, lease, expected_revision=0),
        )

    assert _events_store(postgres_dsn, workspace_namespace).list_for_session(session_id) == [
        created
    ]
    assert _store(postgres_dsn, workspace_namespace).get_workspace(session_id) is None


def test_worker_commit_rejects_stale_expected_stream_revision_without_writes(
    postgres_dsn: str,
    workspace_namespace: str,
) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    lease = _seed_session(postgres_dsn, workspace_namespace, created)

    with pytest.raises(PostgresWorkspaceProjectionConflictError, match="canonical Event"):
        _store(postgres_dsn, workspace_namespace).commit_worker_event(
            prepared,
            rebuild_session([created, prepared]),
            rebuild_workspace([created, prepared]),
            authority=_authority(workspace_namespace, lease, expected_revision=-1),
        )

    assert _events_store(postgres_dsn, workspace_namespace).list_for_session(session_id) == [
        created
    ]
    assert _store(postgres_dsn, workspace_namespace).get_workspace(session_id) is None


def test_workspace_replay_is_monotonic_and_content_idempotent(
    postgres_dsn: str,
    workspace_namespace: str,
) -> None:
    session_id = new_session_id()
    created, prepared, started = _events(session_id, include_started=True)
    event_store = _events_store(postgres_dsn, workspace_namespace)
    for event in (created, prepared, started):
        event_store.append(event)
    workspace = rebuild_workspace([created, prepared, started])
    store = _store(postgres_dsn, workspace_namespace)

    assert store.save_workspace(workspace) == workspace
    assert store.save_workspace(workspace) == workspace

    with pytest.raises(PostgresWorkspaceProjectionConflictError, match="same sequence"):
        store.save_workspace(workspace.model_copy(update={"workspace_root": "/tmp/conflict"}))
    with pytest.raises(PostgresWorkspaceProjectionConflictError, match="stale"):
        store.save_workspace(rebuild_workspace([created, prepared]))
    with pytest.raises(PostgresWorkspaceProjectionConflictError, match="ahead"):
        store.save_workspace(workspace.model_copy(update={"current_sequence": 3}))

    assert store.get_workspace(session_id) == workspace


@pytest.mark.parametrize("stale_component", ["epoch", "token", "owner"])
def test_stale_worker_fence_rolls_back_every_write(
    postgres_dsn: str,
    workspace_namespace: str,
    stale_component: str,
) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    stale_fence = _stale_fence(lease.fence, stale_component)
    store = _store(postgres_dsn, workspace_namespace)

    with pytest.raises(LeaseLostError):
        store.commit_worker_event(
            prepared,
            rebuild_session([created, prepared]),
            rebuild_workspace([created, prepared]),
            authority=WorkerMutationAuthority(
                deployment_namespace=workspace_namespace,
                session_id=session_id,
                lease_fence=stale_fence,
                expected_stream_revision=0,
            ),
        )

    assert _events_store(postgres_dsn, workspace_namespace).list_for_session(session_id) == [
        created
    ]
    assert store.get_workspace(session_id) is None
    assert _sessions(postgres_dsn, workspace_namespace).get_session(session_id) == rebuild_session(
        [created]
    )


def test_worker_authority_scope_must_match_store_and_event(
    postgres_dsn: str,
    workspace_namespace: str,
) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    store = _store(postgres_dsn, workspace_namespace)
    session = rebuild_session([created, prepared])
    workspace = rebuild_workspace([created, prepared])

    with pytest.raises(LeaseLostError, match="namespace"):
        store.commit_worker_event(
            prepared,
            session,
            workspace,
            authority=WorkerMutationAuthority(
                deployment_namespace="another-namespace",
                session_id=session_id,
                lease_fence=lease.fence,
                expected_stream_revision=0,
            ),
        )
    with pytest.raises(LeaseLostError, match="session"):
        store.commit_worker_event(
            prepared,
            session,
            workspace,
            authority=WorkerMutationAuthority(
                deployment_namespace=workspace_namespace,
                session_id=new_session_id(),
                lease_fence=lease.fence,
                expected_stream_revision=0,
            ),
        )

    assert store.get_workspace(session_id) is None


def test_workspace_insert_failure_rolls_back_event_stream_and_session_projection(
    postgres_dsn: str,
    workspace_namespace: str,
) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    lease = _seed_session(postgres_dsn, workspace_namespace, created)
    session = rebuild_session([created, prepared])
    workspace = rebuild_workspace([created, prepared])
    store = _store(postgres_dsn, workspace_namespace)
    authority = _authority(workspace_namespace, lease, expected_revision=0)

    with _workspace_fault(postgres_dsn, workspace_namespace):
        with pytest.raises(psycopg.errors.RaiseException, match="workspace fault"):
            store.commit_worker_event(
                prepared,
                session,
                workspace,
                authority=authority,
            )

    assert _events_store(postgres_dsn, workspace_namespace).list_for_session(session_id) == [
        created
    ]
    assert _sessions(postgres_dsn, workspace_namespace).get_session(session_id) == rebuild_session(
        [created]
    )
    assert store.get_workspace(session_id) is None

    assert store.commit_worker_event(
        prepared,
        session,
        workspace,
        authority=authority,
    ).workspace == workspace


def test_worker_recorder_retries_after_atomic_workspace_failure(
    postgres_dsn: str,
    workspace_namespace: str,
    tmp_path: Path,
) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    event_store = _events_store(postgres_dsn, workspace_namespace)
    for event in (created, prepared):
        event_store.append(event)
    session = rebuild_session([created, prepared])
    workspace = rebuild_workspace([created, prepared])
    session_store = _sessions(postgres_dsn, workspace_namespace)
    session_store.save_session(session)
    workspace_store = _store(postgres_dsn, workspace_namespace)
    workspace_store.save_workspace(workspace)
    lease = PostgresLeaseStore(
        postgres_dsn,
        deployment_namespace=workspace_namespace,
    ).acquire(
        session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(minutes=5),
    )
    index_database = tmp_path / "workspace-indexes.sqlite"
    recorder = DurableHarnessEventRecorder(
        session=session,
        workspace=workspace,
        event_store=event_store,
        projection_store=session_store,
        workspace_store=workspace_store,
        model_call_indexer=ModelCallIndexer(SQLiteModelCallStore(index_database)),
        tool_run_indexer=ToolRunIndexer(
            SQLiteToolRunStore(index_database),
            SQLiteArtifactPayloadStore(index_database),
        ),
        worker_projection_transaction=workspace_store,
        worker_mutation_authority=_authority(
            workspace_namespace,
            lease,
            expected_revision=prepared.sequence,
        ),
    )

    with _workspace_fault(postgres_dsn, workspace_namespace):
        with pytest.raises(psycopg.errors.RaiseException, match="workspace fault"):
            recorder.append(
                EventType.HARNESS_ATTEMPT_STARTED,
                EventActor.HARNESS,
                {"attempt_number": 1},
            )

    assert recorder.session.current_sequence == prepared.sequence
    assert event_store.list_for_session(session_id) == [created, prepared]
    assert session_store.get_session(session_id) == session
    assert workspace_store.get_workspace(session_id) == workspace

    stored = recorder.append(
        EventType.HARNESS_ATTEMPT_STARTED,
        EventActor.HARNESS,
        {"attempt_number": 1},
    )

    assert recorder.session.current_sequence == stored.sequence
    assert session_store.get_session(session_id) == recorder.session
    assert workspace_store.get_workspace(session_id) == recorder.workspace


def test_workspace_projection_isolated_by_deployment_namespace(postgres_dsn: str) -> None:
    session_id = new_session_id()
    created, prepared = _events(session_id)
    namespaces = (f"workspace-a-{uuid4()}", f"workspace-b-{uuid4()}")
    try:
        for namespace in namespaces:
            bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
            event_store = _events_store(postgres_dsn, namespace)
            event_store.append(created)
            event_store.append(prepared)
        first = rebuild_workspace([created, prepared])
        second = first.model_copy(update={"workspace_root": "/tmp/other"})

        _store(postgres_dsn, namespaces[0]).save_workspace(first)
        _store(postgres_dsn, namespaces[1]).save_workspace(second)

        assert _store(postgres_dsn, namespaces[0]).get_workspace(session_id) == first
        assert _store(postgres_dsn, namespaces[1]).get_workspace(session_id) == second
    finally:
        for namespace in namespaces:
            _delete_namespace(postgres_dsn, namespace)


def _events(
    session_id: SessionId,
    *,
    include_started: bool = False,
) -> tuple[SessionEvent, ...]:
    created_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    events = (
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "Workspace PG"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Workspace PG",
                "user_input": "continue",
                "workspace_root": "/tmp/workspace-pg",
                "policy_profile": "workspace_write",
                "tool_profile": "general",
                "network_profile": "domain-allowlist",
                "network_allowlist": ["api.example.com"],
                "mcp_allowlist": ["mcp.github.review"],
                "skill_components": ["review"],
            },
            idempotency_key="workspace-prepared",
            created_at=created_at,
        ),
    )
    if not include_started:
        return events
    return (
        *events,
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        ),
    )


def _seed_session(dsn: str, namespace: str, created: SessionEvent) -> WorkerLease:
    _events_store(dsn, namespace).append(created)
    _sessions(dsn, namespace).save_session(rebuild_session([created]))
    return PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        created.session_id,
        owner_instance_id="worker-a",
        ttl=timedelta(minutes=5),
    )


def _authority(
    namespace: str,
    lease: WorkerLease,
    *,
    expected_revision: int,
) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace=namespace,
        session_id=lease.session_id,
        lease_fence=lease.fence,
        expected_stream_revision=expected_revision,
    )


def _stale_fence(fence: LeaseFence, component: str) -> LeaseFence:
    if component == "epoch":
        updates: dict[str, object] = {"control_plane_epoch": uuid4()}
    elif component == "token":
        updates = {"fencing_token": fence.fencing_token + 1}
    else:
        updates = {"owner_instance_id": "worker-b"}
    return LeaseFence.model_validate({**fence.model_dump(), **updates})


def _store(dsn: str, namespace: str) -> PostgresWorkspaceProjectionStore:
    return PostgresWorkspaceProjectionStore(dsn, deployment_namespace=namespace)


def _events_store(dsn: str, namespace: str) -> PostgresEventStore:
    return PostgresEventStore(dsn, deployment_namespace=namespace)


def _sessions(dsn: str, namespace: str) -> PostgresProjectionStore:
    return PostgresProjectionStore(dsn, deployment_namespace=namespace)


@contextmanager
def _workspace_fault(dsn: str, namespace: str) -> Iterator[None]:
    function_name = sql.Identifier(f"fail_workspace_{uuid4().hex}")
    trigger_name = sql.Identifier(f"fail_workspace_trigger_{uuid4().hex}")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE FUNCTION {}() RETURNS trigger AS $$
                BEGIN
                    IF NEW.deployment_namespace = {} THEN
                        RAISE EXCEPTION 'workspace fault';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            ).format(function_name, sql.Literal(namespace))
        )
        connection.execute(
            sql.SQL(
                "CREATE TRIGGER {} BEFORE INSERT OR UPDATE ON workspace_projections "
                "FOR EACH ROW EXECUTE FUNCTION {}()"
            ).format(trigger_name, function_name)
        )
    try:
        yield
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("DROP TRIGGER IF EXISTS {} ON workspace_projections").format(
                    trigger_name
                )
            )
            connection.execute(sql.SQL("DROP FUNCTION IF EXISTS {}()").format(function_name))


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        for table in (
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
