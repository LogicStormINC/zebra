"""Real coalesced-frontier claims on isolated owned schemas, with no Event body reads."""

from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.migration_runner import apply_postgres_migrations
from agent_storage.postgres.stream_hint_relay import claim_stream_hints, settle_stream_hint
from agent_storage.postgres.task_io import TaskIoConnection
from agent_storage.postgres.work_unit import postgres_work_unit

from tests.agent_storage.test_coverage_artifact_publication import (
    publication as _publication_fixture,
)
from tests.agent_storage.test_postgres_command_wakeup import dsn as _coverage_dsn_fixture
from tests.agent_storage.test_postgres_coverage import env as _postgres_env_fixture
from tests.agent_storage.test_postgres_migrations import (
    isolated_migration_dsn as _isolated_migration_dsn_fixture,
)
from tests.agent_storage.test_postgres_migrations import (
    postgres_dsn as _postgres_dsn_fixture,
)

publication = _publication_fixture
postgres_env = _postgres_env_fixture
dsn = _coverage_dsn_fixture

isolated_migration_dsn = _isolated_migration_dsn_fixture
postgres_dsn = _postgres_dsn_fixture


@pytest.fixture
def relay(isolated_migration_dsn):
    apply_postgres_migrations(isolated_migration_dsn)
    return isolated_migration_dsn, f"relay-{uuid4().hex}"


def append(dsn, ns, sid, sequence):
    PostgresEventStore(dsn, deployment_namespace=ns).append(
        SessionEvent.create(
            session_id=sid,
            sequence=sequence,
            actor=EventActor.SYSTEM,
            event_type=EventType.SESSION_CREATED
            if sequence == 0
            else EventType.USER_MESSAGE_RECEIVED,
            payload={"title": "relay"} if sequence == 0 else {"content": "private source body"},
        )
    )


def claim(dsn, ns, owner="first", **kwargs):
    return claim_stream_hints(dsn, namespace=ns, owner=owner, **kwargs)


def test_sequence_zero_pending_fresh_connection_and_newer_append(relay, monkeypatch):
    dsn, ns = relay
    sid = SessionId(uuid4())
    append(dsn, ns, sid, 0)
    connections = []
    connect = PostgresDatabase.connect_task_io

    def fresh(self, **kwargs):
        conn = connect(self, **kwargs)
        connections.append(conn)
        assert isinstance(conn, TaskIoConnection)
        return conn

    monkeypatch.setattr(PostgresDatabase, "connect_task_io", fresh)
    (old,) = claim(dsn, ns)
    assert old.through == 0 and all(c.closed for c in connections)
    assert claim(dsn, ns, "second") == ()
    assert claim(dsn, ns + "-foreign") == ()
    append(dsn, ns, sid, 1)
    assert not settle_stream_hint(dsn, replace(old, owner="wrong"), confirmed=True)
    assert not settle_stream_hint(dsn, replace(old, through=1), confirmed=True)
    assert settle_stream_hint(dsn, old, confirmed=True)
    (new,) = claim(dsn, ns)
    assert new.through == 1 and new.fence == old.fence + 1
    assert not settle_stream_hint(dsn, old, confirmed=True)
    assert settle_stream_hint(dsn, new, confirmed=True)
    assert claim(dsn, ns) == () and all(c.closed for c in connections)


def test_expiry_fenced_reclaim_and_failed_retry(relay):
    dsn, ns = relay
    sid = SessionId(uuid4())
    append(dsn, ns, sid, 0)
    (old,) = claim(dsn, ns)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_streams SET lease_expires_at=clock_timestamp()-interval '1s' "
            "WHERE deployment_namespace=%s",
            (ns,),
        )
    assert not settle_stream_hint(dsn, old, confirmed=True)
    (new,) = claim(dsn, ns, "second")
    assert new.fence == old.fence + 1
    assert not settle_stream_hint(dsn, old, confirmed=True)
    assert settle_stream_hint(dsn, new, confirmed=False)
    assert claim(dsn, ns) == ()
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_streams SET next_attempt_at='epoch' WHERE deployment_namespace=%s",
            (ns,),
        )
    (again,) = claim(dsn, ns)
    assert again.fence == new.fence + 1 and again.through == 0


def test_borrowed_transaction_rejected_without_ending_caller(relay):
    dsn, ns = relay
    database = PostgresDatabase(dsn, deployment_namespace=ns)
    sid = SessionId(uuid4())
    with pytest.raises(RuntimeError, match="rollback"):
        with postgres_work_unit(database):
            append(dsn, ns, sid, 0)
            with pytest.raises(RuntimeError, match="cannot borrow"):
                claim(dsn, ns)
            # Rejection must not enter/exit or fail the borrowed wrapper.
            append(dsn, ns, sid, 1)
            raise RuntimeError("rollback")
    assert claim(dsn, ns) == ()


@pytest.mark.parametrize("changes", ["published_through=2", "claim_fence=-1", "claim_owner='only'"])
def test_database_claim_shape_rejects_partial_or_ahead(relay, changes):
    dsn, ns = relay
    append(dsn, ns, SessionId(uuid4()), 0)
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_streams SET " + changes + " WHERE deployment_namespace=%s", (ns,)
        )


def test_due_indexes_exclude_acked_backoff_and_live_leases(relay, monkeypatch):
    dsn, ns = relay
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """INSERT INTO session_streams(
          deployment_namespace,session_id,current_version,
          published_through,next_attempt_at) SELECT %s,gen_random_uuid(),1,1,'epoch'
          FROM generate_series(1,4000)""",
            (ns,),
        )
        connection.execute(
            """INSERT INTO session_streams(
          deployment_namespace,session_id,current_version,
          next_attempt_at) SELECT %s,gen_random_uuid(),0,clock_timestamp()+interval '1 day'
          FROM generate_series(1,4000)""",
            (ns,),
        )
        connection.execute(
            """INSERT INTO session_streams(
          deployment_namespace,session_id,current_version,
          claim_owner,claim_fence,claimed_through,lease_expires_at)
          SELECT %s,gen_random_uuid(),0,'leased',1,0,clock_timestamp()+interval '1 day'
          FROM generate_series(1,4000)""",
            (ns,),
        )
        connection.execute("ANALYZE session_streams")
    append(dsn, ns, SessionId(uuid4()), 0)
    queries = []
    execute = psycopg.Cursor.execute

    def observe(cursor, query, params=None, **kwargs):
        if isinstance(query, str) and query.startswith("SELECT session_id,current_version"):
            queries.append((query, params))
        return execute(cursor, query, params, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", observe)
    assert len(claim(dsn, ns)) == 1
    assert len(queries) == 2
    for query, params in queries:
        with psycopg.connect(dsn) as connection:
            (plan,) = connection.execute(
                "EXPLAIN (ANALYZE,FORMAT JSON) " + query, params
            ).fetchone()

            def nodes(node):
                yield node
                for child in node.get("Plans", []):
                    yield from nodes(child)

            indexes = [n for n in nodes(plan[0]["Plan"]) if "Index Name" in n]
            assert indexes and all(n["Index Name"].startswith("stream_hint_") for n in indexes)
            assert (
                sum(n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0) for n in indexes)
                <= 32
            )


def test_migration_cutover_rollback_and_historical_checksum_identity(
    isolated_migration_dsn, monkeypatch
):
    from agent_storage.postgres import migration_runner as migrations
    from agent_storage.postgres.stream_hint_relay_migration import STREAM_HINT_RELAY_MIGRATION

    dsn, namespace = isolated_migration_dsn, "cutover-" + uuid4().hex
    before = tuple(m for m in migrations.MIGRATIONS if m.version <= 100)
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "MIGRATIONS", before)
        apply_postgres_migrations(dsn)
    sid = SessionId(uuid4())
    append(dsn, namespace, sid, 0)
    with pytest.raises(RuntimeError, match="rollback"), psycopg.connect(dsn) as connection:
        for statement in STREAM_HINT_RELAY_MIGRATION.statements:
            connection.execute(statement)
        raise RuntimeError("rollback")
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND table_name='session_streams' "
                "AND column_name='published_through'"
            ).fetchone()[0]
            == 0
        )
        original = connection.execute(
            "SELECT version,name,checksum FROM zebra_schema_migrations ORDER BY version"
        ).fetchall()
    apply_postgres_migrations(dsn)
    apply_postgres_migrations(dsn)
    with psycopg.connect(dsn) as connection:
        current = connection.execute(
            "SELECT version,name,checksum FROM zebra_schema_migrations "
            "WHERE version<=100 ORDER BY version"
        ).fetchall()
        assert current == original
    assert claim(dsn, namespace) == ()  # Explicit historical exclusion, not publication proof.
    append(dsn, namespace, sid, 1)
    assert claim(dsn, namespace)[0].through == 1


@pytest.mark.parametrize("count", [10, 100])
def test_many_canonical_appends_coalesce_without_per_event_relay_rows(
    relay, count, record_property
):
    dsn, namespace = relay
    sid = SessionId(uuid4())
    from time import monotonic

    with psycopg.connect(dsn) as connection:
        start_lsn = connection.execute("SELECT pg_current_wal_insert_lsn()").fetchone()[0]
    started = monotonic()
    for sequence in range(count):
        append(dsn, namespace, sid, sequence)
    record_property("canonical_append_count", count)
    record_property("canonical_append_seconds", monotonic() - started)
    with psycopg.connect(dsn) as connection:
        wal = connection.execute(
            "SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(),%s)", (start_lsn,)
        ).fetchone()[0]
        record_property("whole_append_wal_bytes", int(wal))
    (pending,) = claim(dsn, namespace)
    assert pending.through == count - 1
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM session_streams WHERE deployment_namespace=%s", (namespace,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM broker_outbox WHERE deployment_namespace=%s", (namespace,)
            ).fetchone()[0]
            == 0
        )


def test_supplement_concurrent_claimants_expiry_stale_settle(relay, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from psycopg import Connection

    dsn, namespace = relay
    sessions = [SessionId(uuid4()), SessionId(uuid4())]
    for sid in sessions:
        append(dsn, namespace, sid, 0)
    barrier = Barrier(2)
    commit = Connection.commit

    def simultaneous(connection):
        barrier.wait(timeout=3)
        return commit(connection)

    with monkeypatch.context() as patch:
        patch.setattr(TaskIoConnection, "commit", simultaneous)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(claim, dsn, namespace, "claimant-a", limit=1)
            b = pool.submit(claim, dsn, namespace, "claimant-b", limit=1)
            results = a.result(timeout=5) + b.result(timeout=5)
    assert len(results) == 2 and {c.session_id for c in results} == set(sessions)
    old = results[0]
    append(dsn, namespace, old.session_id, 1)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_streams SET lease_expires_at=clock_timestamp()-interval '1s' "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (namespace, old.session_id),
        )
    (reclaimed,) = claim(dsn, namespace, "fresh-owner")
    assert reclaimed.through == 1 and reclaimed.fence == old.fence + 1
    assert not settle_stream_hint(dsn, old, confirmed=True)
    assert settle_stream_hint(dsn, reclaimed, confirmed=True)


@pytest.mark.parametrize("phase", ["before_publish", "before_settle"])
def test_supplement_actual_process_kill_and_fresh_restart(relay, phase):
    import os
    import subprocess
    import sys
    from select import select

    from agent_integrations.redis_live_fanout import RedisLiveEventFanout

    dsn, namespace = relay
    sid = SessionId(uuid4())
    append(dsn, namespace, sid, 0)
    store = PostgresEventStore(dsn, deployment_namespace=namespace)
    for sequence, kind, payload in (
        (1, EventType.TASK_PREPARED, {"title": "relay", "user_input": "inspect"}),
        (2, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (3, EventType.SESSION_COMPLETED, {}),
    ):
        store.append(
            SessionEvent.create(
                session_id=sid,
                sequence=sequence,
                actor=EventActor.SYSTEM,
                event_type=kind,
                payload=payload,
            )
        )
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.sessions import SessionStatus

    assert rebuild_session(store.list_for_session(sid)).status is SessionStatus.COMPLETED
    url = os.environ["ZEBRA_STREAM_TEST_REDIS_URL"]
    reader = RedisLiveEventFanout.from_url(url)
    barrier = reader.capture_frontier_barrier(deployment_namespace=namespace, session_id=sid)
    code = """import os, sys
from datetime import timedelta
from agent_runtime import stream_hint_relay as runtime
from agent_integrations.redis_live_fanout import RedisLiveEventFanout

real_claim = runtime.claim_stream_hints
runtime.claim_stream_hints = lambda *a, **k: real_claim(*a, **k, ttl=timedelta(seconds=0.2))
publisher = RedisLiveEventFanout.from_url(os.environ["ZEBRA_STREAM_TEST_REDIS_URL"])
phase = os.environ["RELAY_TEST_PHASE"]


def stop():
    print("BARRIER", flush=True)
    sys.stdin.readline()


if phase == "before_publish":
    original = publisher.publish_frontier

    def publish(**kw):
        stop()
        return original(**kw)

    publisher.publish_frontier = publish
elif phase == "before_settle":
    original = runtime.settle_stream_hint

    def settle(*a, **k):
        stop()
        return original(*a, **k)

    runtime.settle_stream_hint = settle
relay = runtime.StreamHintRelay(
    os.environ["RELAY_TEST_DSN"], os.environ["RELAY_TEST_NAMESPACE"], publisher
)
print("RESULT", relay.tick(), flush=True)
relay.close()
"""
    env = {
        **os.environ,
        "RELAY_TEST_DSN": dsn,
        "RELAY_TEST_NAMESPACE": namespace,
        "RELAY_TEST_PHASE": phase,
    }
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert select([child.stdout], [], [], 5)[0]
        assert child.stdout.readline().strip() == b"BARRIER"
        child.kill()  # Actual SIGKILL of this owned child, not a Python exception.
        assert child.wait(timeout=5) == -9
        from time import sleep

        sleep(0.25)
        env["RELAY_TEST_PHASE"] = "restart"
        restarted = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, timeout=5, check=True
        )
        assert restarted.stdout.strip() == b"RESULT 1"
        cursor = reader.wait_frontier_after(
            deployment_namespace=namespace, session_id=sid, barrier=barrier, block_ms=1
        )
        assert cursor != barrier
        with psycopg.connect(dsn) as connection:
            assert connection.execute(
                "SELECT current_version,published_through,claim_fence "
                "FROM session_streams WHERE deployment_namespace=%s AND session_id=%s",
                (namespace, sid),
            ).fetchone() == (3, 3, 2)
            assert connection.execute(
                "SELECT count(*),count(DISTINCT event_id) FROM session_events "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (namespace, sid),
            ).fetchone() == (4, 4)
        assert claim(dsn, namespace) == ()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        reader._client.delete(barrier.stream_ref)
        reader.close()


def test_supplement_migration_blocks_writer_and_preserves_postcutover_pending(
    isolated_migration_dsn, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from agent_storage.postgres import migration_runner
    from agent_storage.postgres.stream_hint_relay_migration import STREAM_HINT_RELAY_MIGRATION

    dsn, namespace = isolated_migration_dsn, "blocked-" + uuid4().hex
    with monkeypatch.context() as patch:
        patch.setattr(
            migration_runner,
            "MIGRATIONS",
            tuple(m for m in migration_runner.MIGRATIONS if m.version <= 100),
        )
        apply_postgres_migrations(dsn)
    sid = SessionId(uuid4())
    append(dsn, namespace, sid, 0)
    entered, writer_pid = Event(), []

    def writer():
        from agent_storage.postgres.events import append_event_in_transaction

        with PostgresDatabase(dsn, deployment_namespace=namespace).connect_task_io() as connection:
            writer_pid.append(connection.info.backend_pid)
            entered.set()
            append_event_in_transaction(
                connection,
                namespace,
                SessionEvent.create(
                    session_id=sid,
                    sequence=1,
                    event_type=EventType.USER_MESSAGE_RECEIVED,
                    actor=EventActor.SYSTEM,
                    payload={"content": "postcutover"},
                ),
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(dsn) as connection:
            connection.execute(STREAM_HINT_RELAY_MIGRATION.statements[0])
            pending = pool.submit(writer)
            assert entered.wait(1) and not pending.done()
            from time import monotonic, sleep

            until = monotonic() + 1
            with psycopg.connect(dsn) as observer:
                while not observer.execute(
                    "SELECT pg_blocking_pids(%s)", (writer_pid[0],)
                ).fetchone()[0]:
                    assert monotonic() < until
                    sleep(0.01)
            for statement in STREAM_HINT_RELAY_MIGRATION.statements[1:]:
                connection.execute(statement)
            assert not pending.done()
        pending.result(timeout=3)
    (ready,) = claim(dsn, namespace)
    assert ready.through == 1
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute(
                "SELECT published_through FROM session_streams WHERE "
                "deployment_namespace=%s AND session_id=%s",
                (namespace, sid),
            ).fetchone()[0]
            == 0
        )


def test_supplement_real_coverage_batch_rollback_commit_frontier(publication, monkeypatch):
    import os

    from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
    from agent_integrations.redis_live_fanout import RedisLiveEventFanout
    from agent_runtime.stream_hint_relay import StreamHintRelay
    from agent_storage.postgres import coverage_artifact_publication as module
    from agent_storage.postgres.work_unit import borrow_work_unit

    from tests.agent_storage.test_coverage_publication_io_authority import _payloads, _publish
    from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE

    env = publication
    fanout = RedisLiveEventFanout.from_url(os.environ["ZEBRA_STREAM_TEST_REDIS_URL"])
    relay = StreamHintRelay(env.dsn, NAMESPACE, fanout)
    assert relay.tick() == 1  # Deliver fixture prefix before testing the batch-only CAS mutator.
    barrier = fanout.capture_frontier_barrier(
        deployment_namespace=NAMESPACE, session_id=env.session.session_id
    )
    original, finalized, borrowed = module.finalize_batch, [False], []

    def actual(*args):
        borrowed.append(borrow_work_unit((env.dsn, NAMESPACE)) is not None)
        result = original(*args)
        finalized[0] = True
        return result

    def reject():
        if finalized[0]:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    monkeypatch.setattr(module, "finalize_batch", actual)
    try:
        with pytest.raises(CoverageRefusedError):
            _publish(env, _payloads(env), reject)
        assert relay.tick() == 0
        assert (
            fanout.capture_frontier_barrier(
                deployment_namespace=NAMESPACE, session_id=env.session.session_id
            )
            == barrier
        )
        records = _publish(env, _payloads(env), lambda: None)
        assert len(records) == 2 and borrowed == [True, True]
        assert relay.tick() == 1
        assert (
            fanout.wait_frontier_after(
                deployment_namespace=NAMESPACE,
                session_id=env.session.session_id,
                barrier=barrier,
                block_ms=1,
            )
            != barrier
        )
        key = barrier.stream_ref
        assert all(
            set(fields) == {"schema_version", "namespace", "session_id", "through_sequence"}
            for _, fields in fanout._client.xrange(key)
        )
    finally:
        fanout._client.delete(barrier.stream_ref)
        relay.close()
