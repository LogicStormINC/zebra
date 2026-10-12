"""One real publication budget: locks, native I/O, auxiliary calls and shutdown."""

import os
import socket
from datetime import timedelta
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType
from agent_core.harness import public_output_lifecycle as lifecycle
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_storage import (
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
    postgres_control_plane_stores,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.task_io import (
    TaskIoConnection,
    current_task_io_deadline,
    task_io_deadline,
)
from agent_storage.postgres.worker_replay_reader import PostgresWorkerReplayReader
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.progress_recovery import recover_worker_progress
from zebra_agent_worker.public_output_runtime import publication_lock, publication_scope
from zebra_agent_worker.tool_run_index import ToolRunIndexer
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory

from tests.agent_core.test_public_expression import completion, expression
from tests.agent_core.test_public_output import draft, verified_facts
from tests.agent_storage.test_worker_progress import append_progress, seed_progress
from tests.test_cloud_api_worker_profile_composition import _cloud_settings
from tests.worker.test_recorder_append_guards import _recorder


@pytest.fixture
def short_budget(monkeypatch):
    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_IO_SECONDS", 0.12)
    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_CLOSE_SECONDS", 0.5)


def hold(lock):
    entered, release = Event(), Event()

    def own():
        with lock:
            entered.set()
            assert release.wait(2), "probe owner must always release its lock"

    thread = Thread(target=own)
    thread.start()
    assert entered.wait(1)
    return thread, release


def test_close_reports_an_unresponsive_owner_without_claiming_detachment(short_budget):
    sink = ProgressiveEventSink(
        lambda _: None,
        user_input="Read",
        policy=PublicOutputPolicy(),
        emission_scope=publication_scope,
    )
    owner, release = hold(sink._lock)
    started = monotonic()
    try:
        with pytest.raises(TimeoutError, match="public output lock deadline"):
            sink.close()
        assert monotonic() - started < 0.7
        assert owner.is_alive() and sink._closing.is_set()
        # A still-running owner is an explicit cleanup failure, not a success flag.
        assert not sink._closed
    finally:
        release.set()
        owner.join(1)
        sink.close()


@pytest.mark.parametrize("path", ["append", "mutation"])
def test_real_recorder_lock_wait_expires_without_a_late_public_write(tmp_path, short_budget, path):
    stores, recorder, session_id = _recorder(tmp_path)
    owner, release = hold(recorder._mutation_lock)
    entered = Event()

    def emit(event):
        entered.set()
        if path == "mutation":
            with recorder.mutation():
                recorder.append_draft(event)
        else:
            recorder.append_draft(event)

    sink = ProgressiveEventSink(
        emit,
        user_input="Read",
        policy=PublicOutputPolicy(wait_seconds=0.01),
        emission_scope=publication_scope,
    )
    sink.operation_started("slow")
    timer = sink._timer
    assert timer is not None
    assert entered.wait(1)
    started = monotonic()
    try:
        with pytest.raises(TimeoutError, match="publication mutation lock deadline"):
            sink.close()
        assert monotonic() - started < 0.7 and not timer.is_alive()
    finally:
        release.set()
        owner.join(1)
        timer.join(1)
        # A failed callback must never get a successful retry during cleanup.
        if sink._timer_error is not None:
            with pytest.raises(TimeoutError):
                sink.close()
        else:
            sink.close()
    assert not any(
        event.event_type is EventType.PUBLIC_OUTPUT
        for event in stores.events.list_for_session(session_id)
    )


def test_progress_persist_and_both_recoveries_share_the_same_deadline(tmp_path):
    tasks, events, scope = seed_progress(tmp_path / "progress.sqlite")
    recovery = recover_worker_progress(
        tasks=tasks, namespace="local", session_id=scope.task_id, ownership_check=lambda: None
    )
    deadlines = []
    recovery.ownership_check = lambda: deadlines.append(current_task_io_deadline())

    def append(event):
        deadlines.append(current_task_io_deadline())
        append_progress(events, scope, event.event_type, event.payload)

    deadline = monotonic() + 1
    with task_io_deadline(deadline):
        recovery.persist_with(append)(draft(EventType.SESSION_TITLE_UPDATED, title="Changed"))
    assert len(deadlines) >= 3 and set(deadlines) == {deadline}
    assert recovery.head.through_sequence == 2


def test_progress_lock_cannot_outlive_the_native_publication_budget(tmp_path, short_budget):
    tasks, _, scope = seed_progress(tmp_path / "progress-lock.sqlite")
    recovery = recover_worker_progress(
        tasks=tasks, namespace="local", session_id=scope.task_id, ownership_check=lambda: None
    )
    owner, release = hold(recovery._lock)
    writes = []
    sink = ProgressiveEventSink(
        recovery.persist_with(writes.append),
        user_input="Read",
        policy=PublicOutputPolicy(wait_seconds=0.01),
        emission_scope=publication_scope,
    )
    sink.operation_started("slow")
    timer = sink._timer
    assert timer is not None
    try:
        timer.join(0.4)
        with pytest.raises(TimeoutError, match="publication mutation lock deadline"):
            sink.close()
        assert not timer.is_alive() and writes == []
    finally:
        release.set()
        owner.join(1)
        with pytest.raises(TimeoutError):
            sink.close()


def test_native_timer_scope_includes_dedup_and_connection_handshake(short_budget):
    accepted, disconnected = Event(), Event()
    deadlines = []
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(1)

        def peer():
            with server.accept()[0] as connection:
                accepted.set()
                connection.settimeout(1)
                while connection.recv(65536):
                    pass
            disconnected.set()

        receiver = Thread(target=peer)
        receiver.start()
        database = PostgresDatabase(
            make_conninfo(host="127.0.0.1", port=server.getsockname()[1], sslmode="disable"),
            deployment_namespace="public-deadline",
        )

        def dedup(_):
            deadlines.append(current_task_io_deadline())
            assert Event().wait(0.02) is False
            return False

        def emit(event):
            deadlines.append(current_task_io_deadline())
            database.connect_task_io()  # Default 2 seconds must inherit the remaining 0.12.

        sink = ProgressiveEventSink(
            emit,
            user_input="Read",
            policy=PublicOutputPolicy(wait_seconds=0.01),
            emission_scope=publication_scope,
            output_published=dedup,
        )
        sink.operation_started("slow")
        timer = sink._timer
        assert timer is not None
        try:
            assert accepted.wait(1)
            started = monotonic()
            with pytest.raises(TimeoutError, match="Task storage"):
                sink.close()
            assert monotonic() - started < 0.5
            assert disconnected.wait(0.5)
            assert len(deadlines) == 2 and len(set(deadlines)) == 1
            assert not timer.is_alive()
        finally:
            receiver.join(1)
            with pytest.raises(TimeoutError):
                sink.close()


def test_auxiliary_completion_inherits_remaining_whole_publication_budget(short_budget):
    calls = []
    events = []

    def complete(messages, policy, seconds):
        calls.append(seconds)
        # The provider checks a budget computed immediately before this call.
        assert seconds <= current_task_io_deadline() - monotonic() + 0.005
        return completion('{"order":[0,1],"lead":"none"}')

    sink = ProgressiveEventSink(
        events.append,
        user_input="Read",
        policy=PublicOutputPolicy(),
        expression=expression(complete, events),
        emission_scope=publication_scope,
    )
    try:
        with sink._lock:
            for call_id in ("first", "second", "third"):
                sink(
                    draft(
                        EventType.TOOL_EXECUTION_COMPLETED,
                        tool_call_id=call_id,
                        status="executed",
                        metadata={"public_facts": verified_facts(f"Page {call_id} only.")},
                    )
                )
        timer = sink._evidence_timer
        assert timer is not None
        timer.join(0.4)
        assert calls and 0 < calls[0] <= 0.12
    finally:
        sink.close()


def test_native_mutation_lock_preserves_reentrancy_and_absolute_budget():
    from threading import RLock

    lock = RLock()
    deadline = monotonic() + 0.25
    with task_io_deadline(deadline), publication_lock(lock):
        with publication_lock(lock, bounded=True):
            assert current_task_io_deadline() == deadline


@pytest.mark.parametrize("outer_seconds", [0.1, 3.0])
def test_publication_scope_yields_effective_deadline_to_core(outer_seconds):
    from threading import RLock

    outer = monotonic() + outer_seconds
    proposed = monotonic() + 1
    with task_io_deadline(outer):
        with publication_scope(proposed) as accepted:
            assert accepted == min(outer, proposed)
            assert current_task_io_deadline() == accepted
            with lifecycle.public_output_lock(RLock(), publication_scope):
                assert lifecycle.current_public_output_deadline() == accepted
        assert current_task_io_deadline() == outer
    assert current_task_io_deadline() is None
    assert lifecycle.current_public_output_deadline() is None


@pytest.fixture(scope="module")
def publication_dsn():
    configured = os.environ.get("ZEBRA_PUBLICATION_SCRATCH_DSN")
    if not configured:
        pytest.skip("set ZEBRA_PUBLICATION_SCRATCH_DSN for isolated publication PG proofs")
    params = conninfo_to_dict(configured)
    owned = os.environ.get("ZEBRA_STREAM_TEST_POSTGRES_DSN")
    assert params.get("host") == "127.0.0.1"
    assert params.get("port") == "32768" or (owned and configured == owned)
    schema = f"publication_deadline_{uuid4().hex}"
    with psycopg.connect(configured) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(configured, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(configured) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def native_recorder(dsn, tmp_path):
    namespace = f"publication-{uuid4().hex}"
    cloud = _cloud_settings()
    stores = postgres_control_plane_stores(
        dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Native publication deadline", user_input="Read", workspace_root=tmp_path
        )
    )
    session_id = bootstrap.session.session_id
    for event in bootstrap.events:
        stores.events.append(event)
    source = stores.events.list_for_session(session_id)
    session, workspace = rebuild_session(source), rebuild_workspace(source)
    stores.sessions.save_session(session)
    stores.workspaces.save_workspace(workspace)
    stores.tasks.ensure_for_session(session_id)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    lease = stores.leases.acquire(
        session_id, owner_instance_id="native-publication", ttl=timedelta(seconds=30)
    )
    database = PostgresDatabase(dsn, deployment_namespace=namespace)

    def owned():
        with database.connect_task_io() as connection:
            assert_current_lease_fence(connection, namespace, session_id, lease.fence)

    recorder = WorkerProjectionRecorderFactory(
        stores=stores,
        model_call_indexer=ModelCallIndexer(stores.model_calls),
        tool_run_indexer=ToolRunIndexer(stores.tool_runs),
        transaction=stores.worker_projection_transaction,
        deployment_namespace=namespace,
        tail_reader=PostgresWorkerReplayReader(dsn, deployment_namespace=namespace).tail_page,
    ).build(session=session, workspace=workspace, lease=lease, ownership_check=owned)
    return stores, recorder, source


@pytest.mark.parametrize("stage", ["statement", "commit"])
def test_real_fenced_timer_sql_and_commit_stop_without_late_publication(
    publication_dsn, tmp_path, monkeypatch, stage
):
    label = f"publication-timer-{uuid4().hex}"
    dsn = make_conninfo(publication_dsn, application_name=label)
    stores, recorder, source = native_recorder(dsn, tmp_path)
    name = f"publication_delay_{uuid4().hex}"
    timing = (
        "CREATE CONSTRAINT TRIGGER {} AFTER INSERT ON session_events "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {}()"
        if stage == "commit"
        else "CREATE TRIGGER {} BEFORE INSERT ON session_events FOR EACH ROW EXECUTE FUNCTION {}()"
    )
    with psycopg.connect(dsn) as setup:
        setup.execute(
            sql.SQL(
                "CREATE FUNCTION {}() RETURNS trigger AS $$ BEGIN "
                "IF NEW.event_type='public_output' THEN PERFORM pg_sleep(5); END IF; "
                "RETURN NEW; END; $$ LANGUAGE plpgsql"
            ).format(sql.Identifier(name))
        )
        setup.execute(sql.SQL(timing).format(sql.Identifier(name), sql.Identifier(name)))
    connections = []
    native_connect = PostgresDatabase.connect_task_io

    def capture(database, **kwargs):
        connection = native_connect(database, **kwargs)
        assert isinstance(connection, TaskIoConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(PostgresDatabase, "connect_task_io", capture)
    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_IO_SECONDS", 0.5)
    monkeypatch.setattr(lifecycle, "PUBLIC_OUTPUT_CLOSE_SECONDS", 1.0)
    sink = ProgressiveEventSink(
        recorder.append_draft,
        user_input="Read",
        policy=PublicOutputPolicy(wait_seconds=0.01),
        emission_scope=publication_scope,
    )
    sink.operation_started("slow")
    timer = sink._timer
    assert timer is not None
    try:
        with psycopg.connect(publication_dsn, autocommit=True) as observe:
            observe.execute("SET statement_timeout='1s'")
            until = monotonic() + 1
            while True:
                row = observe.execute(
                    "SELECT query FROM pg_stat_activity "
                    "WHERE application_name=%s AND wait_event='PgSleep'",
                    (label,),
                ).fetchone()
                if row is not None:
                    break
                assert monotonic() < until, (
                    f"native timer did not reach {stage}: {sink._timer_error}"
                )
                Event().wait(0.002)
            assert (row[0].strip().upper() == "COMMIT") == (stage == "commit")
            started = monotonic()
            with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)) as caught:
                sink.close()
            assert caught.value is sink._timer_error
            assert monotonic() - started < 1 and not timer.is_alive()
            assert connections and all(connection.closed for connection in connections)
            assert len({connection.deadline for connection in connections}) == 1
            until = monotonic() + 0.5
            while observe.execute(
                "SELECT 1 FROM pg_stat_activity WHERE application_name=%s", (label,)
            ).fetchone():
                assert monotonic() < until, "native timer backend survived cleanup"
                Event().wait(0.002)
        # The original canonical Event transaction rolled back; no cleanup retry.
        before = len(connections)
        sink.publish("late", "commentary", "evidence", "must not publish")
        assert len(connections) == before
        assert stores.events.list_for_session(recorder.session.session_id) == source
        assert recorder.session.current_sequence == source[-1].sequence
    finally:
        timer.join(1)
        if sink._timer_error is not None:
            with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
                sink.close()
        else:
            sink.close()
        with psycopg.connect(dsn) as cleanup:
            cleanup.execute(
                sql.SQL("DROP TRIGGER {} ON session_events").format(sql.Identifier(name))
            )
            cleanup.execute(sql.SQL("DROP FUNCTION {}()").format(sql.Identifier(name)))
