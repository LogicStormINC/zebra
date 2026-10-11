"""Session recovery bounds, native fences, crash holes and resumable preparation."""

import json
import os
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.session_recovery import (
    SessionEventPage,
    SessionRecoveryCommit,
    SessionRecoveryConflict,
    SessionRecoveryHead,
)
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_core.ports.worker_preparation import PreparationAdvanced
from agent_storage.postgres.command_read_state_migration import COMMAND_READ_STATE_MIGRATION
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.leases import PostgresLeaseStore
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.projections import PostgresProjectionStore
from agent_storage.postgres.session_recovery import (
    SESSION_PAGE_METADATA_SQL,
    PostgresSessionRecoveryStore,
)
from agent_storage.postgres.session_recovery_migration import SESSION_RECOVERY_MIGRATION
from agent_storage.postgres.task_event_bytes_migration import TASK_EVENT_BYTES_MIGRATION
from agent_storage.postgres.workspaces import PostgresWorkspaceProjectionStore
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from zebra_agent_worker.bounded_session_recovery import (
    SessionRecoveryPending,
    recover_cloud_session,
)
from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.recovery import SessionRecoveryService

NS = "session-recovery-probe"


class RecoveryStore(PostgresSessionRecoveryStore):
    def __init__(self, dsn: str, namespace: str = NS) -> None:
        super().__init__(dsn, deployment_namespace=namespace)


@pytest.fixture
def native():
    configured = os.environ.get("ZEBRA_HEADER_SCRATCH_DSN")
    if not configured:
        pytest.skip("set ZEBRA_HEADER_SCRATCH_DSN to an isolated header_scratch PostgreSQL")
    settings = conninfo_to_dict(configured)
    assert settings.get("dbname") == "header_scratch"
    assert settings.get("host") in {"127.0.0.1", "localhost"}
    schema = f"session_recovery_{uuid4().hex}"
    with psycopg.connect(configured, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(configured, options=f"-c search_path={schema},public")
    try:
        with psycopg.connect(dsn) as database:
            for migration in MIGRATIONS:
                if migration.version in {1, 2, 4, 6, 20, 23}:
                    for statement in migration.statements:
                        database.execute(statement)
            for migration in (TASK_EVENT_BYTES_MIGRATION, SESSION_RECOVERY_MIGRATION):
                for statement in migration.statements:
                    database.execute(statement)
            database.execute(COMMAND_READ_STATE_MIGRATION.statements[0])
        yield dsn
    finally:
        # Only the test-owned disposable schema is removed; no application migration.
        with psycopg.connect(configured, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def seed(dsn: str, count: int = 600):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Recovery",
            user_input="continue",
            workspace_root=Path("/tmp/recovery-probe"),
        )
    )
    session_id = bootstrap.session.session_id
    events = PostgresEventStore(dsn, deployment_namespace=NS)
    for event in bootstrap.events:
        events.append(event)
    first = len(bootstrap.events)
    with psycopg.connect(dsn) as database:
        database.execute(
            "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,"
            "event_type,payload,actor,created_at) SELECT %s,md5(%s||n::text)::uuid,%s,n,"
            "'runtime_cleanup_failed','{}'::jsonb,'system',%s "
            "FROM generate_series(%s::bigint,%s::bigint) n",
            (NS, str(session_id), session_id, bootstrap.session.updated_at, first, count - 1),
        )
        database.execute("UPDATE session_streams SET current_version=%s", (count - 1,))
        database.execute("INSERT INTO control_plane_epochs VALUES (%s,%s,now())", (NS, uuid4()))
    projections = PostgresProjectionStore(dsn, deployment_namespace=NS)
    workspaces = PostgresWorkspaceProjectionStore(dsn, deployment_namespace=NS)
    projections.save_session(bootstrap.session)
    workspaces.save_workspace(rebuild_workspace(list(bootstrap.events)))
    leases = PostgresLeaseStore(dsn, deployment_namespace=NS)
    lease = leases.acquire(
        session_id, owner_instance_id="recovery-owner", ttl=timedelta(seconds=30)
    )
    authority = WorkerMutationAuthority(
        deployment_namespace=NS,
        session_id=session_id,
        lease_fence=lease.fence,
        expected_stream_revision=-1,
    )
    return SimpleNamespace(
        dsn=dsn,
        session_id=session_id,
        events=events,
        sessions=projections,
        workspaces=workspaces,
        leases=leases,
        lease=lease,
        authority=authority,
        recovery=RecoveryStore(dsn),
        bootstrap=bootstrap,
    )


def service(state):
    return SessionRecoveryService(
        state.events,
        state.sessions,
        state.workspaces,
        worker_projection_transaction=state.workspaces,
        deployment_namespace=NS,
        model_call_indexer=Mock(),
        tool_run_indexer=Mock(),
        session_recovery_store=state.recovery,
    )


def advance(state, *, expected: int = -1, after: int = -1, highwater: int = 599):
    page = state.recovery.read_session_event_page(
        state.session_id,
        after,
        through_sequence=highwater,
    )
    return state.recovery.commit_session_recovery_page(
        page,
        expected_index_sequence=expected,
        authority=state.authority.model_copy(update={"expected_stream_revision": after}),
    )


@pytest.mark.parametrize("highwater", [1_000, 1])
def test_same_lease_slices_share_deadline_and_never_read_whole_history(monkeypatch, highwater):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Slices",
            user_input="continue",
            workspace_root=Path("/tmp/recovery-slices"),
        )
    )
    session = bootstrap.session.model_copy(update={"current_sequence": 0})
    workspace = rebuild_workspace(list(bootstrap.events)).model_copy(update={"current_sequence": 0})
    store, projections, workspaces = Mock(), Mock(), Mock()
    projections.get_session.return_value = session
    workspaces.get_workspace.return_value = workspace
    store.read_session_recovery_head.return_value = SessionRecoveryHead(highwater, 0)
    if highwater == 1:
        store.read_session_recovery_head.side_effect = [
            SessionRecoveryHead(1, 0),
            TimeoutError("final fenced readiness exceeded deadline"),
        ]
    event = SessionEvent.create(
        session_id=session.session_id,
        sequence=1,
        event_type=EventType.RUNTIME_CLEANUP_FAILED,
        actor=EventActor.SYSTEM,
        payload={"target": "runtime", "error_type": "probe", "attempt_number": 1},
    )
    size = len(
        json.dumps(
            event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    store.read_session_event_page.return_value = SessionEventPage(
        session.session_id,
        (event,),
        0,
        highwater,
        size,
    )
    store.commit_session_recovery_page.return_value = SessionRecoveryCommit(
        session.model_copy(update={"current_sequence": 1}),
        workspace.model_copy(update={"current_sequence": 1}),
        1,
    )
    # The second page never starts: elapsed budget is cumulative across all adapters.
    clock = iter((10.0, 10.5, 12.1))
    monkeypatch.setattr(
        "zebra_agent_worker.bounded_session_recovery.monotonic", lambda: next(clock)
    )
    monkeypatch.setattr("agent_storage.postgres.task_io.monotonic", lambda: 10.0)
    authority = Mock(deployment_namespace=NS)
    with pytest.raises(PreparationAdvanced) as error:
        recover_cloud_session(
            session.session_id, store, projections, workspaces, authority=authority
        )
    assert error.value.through_sequence == 1 and error.value.highwater == highwater
    store.read_session_event_page.assert_called_once_with(
        session.session_id,
        0,
        through_sequence=highwater,
        limit=256,
        max_bytes=1_048_576,
    )
    projections.list_for_session.assert_not_called()
    if highwater == 1:
        # Retry verifies readiness under the same fence without replaying the committed page.
        committed = store.commit_session_recovery_page.return_value
        projections.get_session.return_value = committed.session
        workspaces.get_workspace.return_value = committed.workspace
        store.read_session_recovery_head.side_effect = None
        store.read_session_recovery_head.return_value = SessionRecoveryHead(1, 1)
        monkeypatch.setattr("zebra_agent_worker.bounded_session_recovery.monotonic", lambda: 20.0)
        monkeypatch.setattr("agent_storage.postgres.task_io.monotonic", lambda: 20.0)
        assert recover_cloud_session(
            session.session_id, store, projections, workspaces, authority=authority
        ) == (committed.session, committed.workspace, 1)
        store.commit_session_recovery_page.assert_called_once()
        store.read_session_event_page.assert_called_once()
        assert all(
            call.kwargs["authority"] is authority
            for call in store.read_session_recovery_head.call_args_list
        )


def test_readiness_before_heartbeat_releases_claim_without_deterministic_failure():
    leases, recovery = Mock(), Mock()
    recovery.recover_session.side_effect = SessionRecoveryPending("missing prerequisite")
    claimed = SessionClaimService(leases, recovery)
    from datetime import UTC, datetime

    with pytest.raises(CheckpointNotReady):
        claimed.claim_session(
            uuid4(), worker_id="test", claimed_at=datetime.now(UTC), lease_ttl_seconds=30
        )
    leases.release.assert_called_once()
    leases.heartbeat.assert_not_called()


@pytest.mark.parametrize("size", [1_000, 10_000, 100_000])
def test_native_indexed_pages_and_no_whole_history(native, monkeypatch, size):
    state = seed(native, size)
    monkeypatch.setattr(
        state.events, "list_for_session", Mock(side_effect=AssertionError("history"))
    )
    monkeypatch.setattr(state.events, "read_since", Mock(side_effect=AssertionError("suffix")))
    head = state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    assert head == SessionRecoveryHead(size - 1, -1)
    page = state.recovery.read_session_event_page(
        state.session_id, -1, through_sequence=head.highwater
    )
    assert len(page.events) == 256 and page.byte_count <= 1_048_576
    result = advance(state, highwater=head.highwater)
    assert result.index_sequence == 255
    with psycopg.connect(native, row_factory=dict_row, autocommit=True) as database:
        database.execute("VACUUM ANALYZE session_events")
        plan = database.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + SESSION_PAGE_METADATA_SQL,
            (size - 256, size - 1, NS, state.session_id, 256),
        ).fetchone()["QUERY PLAN"][0]["Plan"]
        assert plan["Actual Rows"] == 256 and plan["Node Type"] == "Limit"

        def nodes(node):
            yield node
            for child in node.get("Plans", ()):
                yield from nodes(child)

        assert any("Index" in node["Node Type"] for node in nodes(plan))
        assert not any(node["Node Type"] == "Seq Scan" for node in nodes(plan))
    # A warm primary/index recovery seeks just its tail even with 100k historical Events.
    with psycopg.connect(native) as database:
        database.execute("UPDATE session_projections SET current_sequence=%s", (size - 2,))
        database.execute("UPDATE workspace_projections SET current_sequence=%s", (size - 2,))
        database.execute("UPDATE session_recovery_frontiers SET index_sequence=%s", (size - 2,))
    recovered = service(state).recover_session(state.session_id, worker_lease=state.lease)
    assert recovered.event_count == size and recovered.last_sequence == size - 1
    state.events.list_for_session.assert_not_called()
    state.events.read_since.assert_not_called()


def test_native_stale_fence_head_empty_recovery_and_atomic_checkpoint(native):
    state = seed(native)
    state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    state.leases.release(state.session_id, fence=state.lease.fence)
    state.leases.acquire(state.session_id, owner_instance_id="new-owner", ttl=timedelta(seconds=30))
    with pytest.raises(LeaseLostError):
        state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    with pytest.raises(LeaseLostError):
        advance(state)
    with psycopg.connect(native) as database:
        assert (
            database.execute("SELECT index_sequence FROM session_recovery_frontiers").fetchone()[0]
            == -1
        )
    with pytest.raises(LeaseLostError):
        service(state).recover_session(state.session_id, worker_lease=state.lease)


@pytest.mark.parametrize("lagging", ["session_projections", "workspace_projections"])
def test_native_primary_divergence_and_primary_ahead_of_index(native, lagging):
    state = seed(native)
    with psycopg.connect(native) as database:
        database.execute(
            "UPDATE session_events SET event_type='model_response_received',payload=%s "
            "WHERE sequence=4",
            (Jsonb({"assistant_message": "missing-index", "tool_call_count": 0}),),
        )
        database.execute(
            "UPDATE session_events SET event_type='tool_execution_completed',payload=%s "
            "WHERE sequence=5",
            (Jsonb({"tool_name": "command.run", "status": "succeeded", "output": "indexed"}),),
        )
        for table in ("session_projections", "workspace_projections"):
            database.execute(
                sql.SQL("UPDATE {} SET current_sequence=%s").format(sql.Identifier(table)),
                (10 if table == lagging else 500,),
            )
    head = state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    assert head.index_sequence == -1  # A primary commit must never stand in for index coverage.
    recovered = service(state).recover_session(state.session_id, worker_lease=state.lease)
    assert recovered.session.current_sequence == recovered.workspace.current_sequence == 599
    with psycopg.connect(native) as database:
        assert database.execute("SELECT count(*) FROM session_events").fetchone()[0] == 600
        assert database.execute("SELECT count(*) FROM model_call_projections").fetchone()[0] == 1
        assert database.execute("SELECT count(*) FROM tool_run_projections").fetchone()[0] == 1
        assert (
            database.execute("SELECT index_sequence FROM session_recovery_frontiers").fetchone()[0]
            == 599
        )


def test_native_crash_before_frontier_rolls_back_indexes_and_primary(native, monkeypatch):
    state = seed(native)
    with psycopg.connect(native) as database:
        database.execute(
            "UPDATE session_events SET event_type='model_response_received',payload=%s "
            "WHERE sequence=4",
            (Jsonb({"assistant_message": "canonical", "tool_call_count": 0}),),
        )
    state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    original = PostgresDatabase.connect_task_io
    from agent_storage.postgres.task_io import TaskIoConnection

    execute = TaskIoConnection.execute

    def crash(connection, query, parameters=None, **kwargs):
        if isinstance(query, str) and "UPDATE session_recovery_frontiers" in query:
            raise RuntimeError("crash between index and frontier")
        return execute(connection, query, parameters, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", crash)
    with pytest.raises(RuntimeError, match="crash between"):
        advance(state)
    monkeypatch.setattr(TaskIoConnection, "execute", execute)
    assert PostgresDatabase.connect_task_io is original
    with psycopg.connect(native) as database:
        assert database.execute("SELECT count(*) FROM model_call_projections").fetchone()[0] == 0
        assert (
            database.execute("SELECT index_sequence FROM session_recovery_frontiers").fetchone()[0]
            == -1
        )
    advance(state)
    with psycopg.connect(native) as database:
        assert (
            database.execute("SELECT assistant_message FROM model_call_projections").fetchone()[0]
            == "canonical"
        )


def test_native_namespace_cas_gap_and_byte_admission(native):
    state = seed(native)
    state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    with pytest.raises(LeaseLostError):
        RecoveryStore(native, "foreign").read_session_recovery_head(
            state.session_id,
            authority=state.authority,
        )
    with psycopg.connect(native) as database:
        database.execute("INSERT INTO session_streams VALUES ('foreign',%s,0)", (state.session_id,))
        database.execute(
            "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,"
            "event_type,payload,actor,created_at) VALUES ('foreign',%s,%s,0,'session_created',"
            "'{\"title\":\"foreign-only\"}','system',now())",
            (uuid4(), state.session_id),
        )
    foreign_page = RecoveryStore(native, "foreign").read_session_event_page(
        state.session_id,
        -1,
        through_sequence=0,
    )
    assert foreign_page.events[0].payload == {"title": "foreign-only"}
    assert (
        state.recovery.read_session_event_page(
            state.session_id,
            -1,
            through_sequence=0,
        )
        .events[0]
        .payload["title"]
        == "Recovery"
    )
    with pytest.raises(SessionRecoveryConflict, match="CAS"):
        advance(state, expected=0)
    with pytest.raises(SessionRecoveryConflict, match="skips"):
        advance(state, after=1)
    with psycopg.connect(native) as database:
        database.execute(
            "UPDATE session_events SET payload=%s WHERE sequence=3",
            (Jsonb({"blob": "图" * 100_000}),),
        )
    page = state.recovery.read_session_event_page(
        state.session_id, -1, through_sequence=599, max_bytes=10_000
    )
    assert page.next_sequence == 2 and page.byte_count <= 10_000
    with pytest.raises(ValueError, match="exceeds the page"):
        state.recovery.read_session_event_page(
            state.session_id, 2, through_sequence=599, max_bytes=10_000
        )
    with psycopg.connect(native) as database:
        database.execute("DELETE FROM session_events WHERE sequence=5")
    with pytest.raises(ValueError, match="gap"):
        state.recovery.read_session_event_page(state.session_id, 4, through_sequence=599)


def test_native_captured_highwater_and_frontier_resume(native):
    state = seed(native)
    head = state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    result = advance(state)
    with psycopg.connect(native) as database:
        database.execute(
            "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,"
            "event_type,payload,actor,created_at) VALUES (%s,%s,%s,600,'runtime_cleanup_failed',"
            "'{}','system',now())",
            (NS, uuid4(), state.session_id),
        )
        database.execute("UPDATE session_streams SET current_version=600")
    resumed = state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    assert resumed.highwater == head.highwater == 599 and resumed.index_sequence == 255
    next_result = advance(state, expected=result.index_sequence, after=255)
    assert next_result.index_sequence == 511
    advance(state, expected=511, after=511)
    assert (
        state.recovery.read_session_recovery_head(
            state.session_id,
            authority=state.authority,
        ).highwater
        == 600
    )


@pytest.mark.parametrize("size", [1_000, 10_000, 100_000])
def test_native_cold_prefixes_finish_under_same_lease_without_canonical_writes(
    native, monkeypatch, size
):
    state = seed(native, size)
    worker = service(state)
    claims = SessionClaimService(state.leases, worker)
    for name in ("list_for_session", "read_since", "append"):
        monkeypatch.setattr(state.events, name, Mock(side_effect=AssertionError(name)))
    with psycopg.connect(native) as database:
        database.execute("""CREATE FUNCTION deny_source_write() RETURNS trigger AS $$ BEGIN
            RAISE EXCEPTION 'recovery must not write canonical source'; END; $$ LANGUAGE plpgsql""")
        database.execute("""CREATE TRIGGER deny_source_write BEFORE INSERT OR UPDATE OR DELETE
            ON session_events FOR EACH ROW EXECUTE FUNCTION deny_source_write()""")
    attempts, prefixes, checkpoints = [], [], []
    recover = worker.recover_session
    heartbeat = state.leases.heartbeat
    release = Mock(wraps=state.leases.release)
    monkeypatch.setattr(state.leases, "release", release)

    def prepare(session_id, *, worker_lease):
        # Force a slice boundary after two real, atomic PG Page commits.
        # Claim recovery now owns the inline slice loop; reset this clock per slice.
        base = time.monotonic()
        clock = iter((base, base + 0.1, base + 0.2, base + 2.1))
        monkeypatch.setattr(
            "zebra_agent_worker.bounded_session_recovery.monotonic", lambda: next(clock)
        )
        attempts.append(worker_lease.fence)
        try:
            return recover(session_id, worker_lease=worker_lease)
        except PreparationAdvanced as progress:
            prefixes.append(progress.through_sequence)
            raise

    def renew(session_id, **kwargs):
        assert kwargs["fence"] == state.lease.fence
        renewed = heartbeat(session_id, **kwargs)
        checkpoints.append(renewed.checkpoint)
        return renewed

    monkeypatch.setattr(worker, "recover_session", prepare)
    monkeypatch.setattr(state.leases, "heartbeat", renew)
    result = claims.recover_lease(state.lease, lease_ttl_seconds=3)
    assert result.lease.fence == state.lease.fence
    assert result.lease.checkpoint == size - 1
    assert result.recovery.last_sequence == size - 1
    release.assert_not_called()
    assert state.leases.get(state.session_id).fence == state.lease.fence
    assert len(attempts) > 1 and len(set(attempts)) == 1
    assert prefixes == sorted(set(prefixes)) and prefixes[-1] < size - 1
    assert checkpoints == sorted(checkpoints) and checkpoints[-1] == size - 1
    assert all(checkpoint in {state.lease.checkpoint, size - 1} for checkpoint in checkpoints)
    claims.release_claim(result)
    release.assert_called_once_with(state.session_id, fence=state.lease.fence)
    with psycopg.connect(native) as database:
        assert database.execute("SELECT count(*) FROM session_events").fetchone()[0] == size
        assert database.execute("SELECT fencing_token FROM worker_leases").fetchone()[0] == 1
        assert (
            database.execute("SELECT index_sequence FROM session_recovery_frontiers").fetchone()[0]
            == size - 1
        )


def test_native_fence_revalidated_after_primary_and_index_before_commit(native, monkeypatch):
    state = seed(native)
    state.recovery.read_session_recovery_head(state.session_id, authority=state.authority)
    import agent_storage.postgres.session_recovery as recovery_storage

    check = recovery_storage.assert_current_lease_fence
    checks = []

    def expires(connection, namespace, session_id, fence):
        checks.append(fence)
        if len(checks) == 2:
            raise LeaseLostError("lease expired after business-row waits")
        return check(connection, namespace, session_id, fence)

    monkeypatch.setattr(recovery_storage, "assert_current_lease_fence", expires)
    with pytest.raises(LeaseLostError, match="expired after"):
        advance(state)
    with psycopg.connect(native) as database:
        assert (
            database.execute("SELECT index_sequence FROM session_recovery_frontiers").fetchone()[0]
            == -1
        )
        assert (
            database.execute("SELECT current_sequence FROM session_projections").fetchone()[0]
            == state.bootstrap.session.current_sequence
        )


def test_native_fully_recovered_empty_suffix_still_rejects_old_lease(native, monkeypatch):
    state = seed(native, 3)
    recovery = service(state)
    recovery.recover_session(state.session_id, worker_lease=state.lease)
    pages = Mock(wraps=state.recovery.read_session_event_page)
    monkeypatch.setattr(state.recovery, "read_session_event_page", pages)
    recovery.recover_session(state.session_id, worker_lease=state.lease)
    pages.assert_not_called()
    state.leases.release(state.session_id, fence=state.lease.fence)
    state.leases.acquire(state.session_id, owner_instance_id="new-owner", ttl=timedelta(seconds=30))
    with pytest.raises(LeaseLostError):
        recovery.recover_session(state.session_id, worker_lease=state.lease)
    pages.assert_not_called()


@pytest.mark.parametrize("primary_ahead", [False, True])
def test_native_source_advanced_during_slice_cannot_hide_new_tail(
    native, monkeypatch, primary_ahead
):
    state = seed(native)
    commit = state.recovery.commit_session_recovery_page
    injected = []

    def append_tail(page, **kwargs):
        if not injected:
            injected.append(True)
            with psycopg.connect(native) as database:
                database.execute(
                    "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,"
                    "event_type,payload,actor,created_at) VALUES (%s,%s,%s,600,"
                    "'runtime_cleanup_failed','{}','system',now())",
                    (NS, uuid4(), state.session_id),
                )
                database.execute("UPDATE session_streams SET current_version=600")
                if primary_ahead:
                    database.execute("UPDATE session_projections SET current_sequence=600")
        return commit(page, **kwargs)

    monkeypatch.setattr(state.recovery, "commit_session_recovery_page", append_tail)
    recovered = service(state).recover_session(state.session_id, worker_lease=state.lease)
    assert recovered.last_sequence == recovered.session.current_sequence == 600
    assert recovered.workspace.current_sequence == 600 and recovered.event_count == 601
    with psycopg.connect(native) as database:
        assert database.execute(
            "SELECT highwater,index_sequence FROM session_recovery_frontiers"
        ).fetchone() == (600, 600)
