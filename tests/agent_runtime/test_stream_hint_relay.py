"""One cumulative budget and owned publisher lifetime, independent of execution."""

from datetime import UTC, datetime
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import SessionId
from agent_integrations.redis_transient_deadlines import current_redis_io_deadline
from agent_runtime import stream_hint_relay as runtime
from agent_storage.postgres.stream_hint_relay import StreamHintClaim
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline
from redis.exceptions import ConnectionError

from tests.agent_storage.test_postgres_migrations import (
    isolated_migration_dsn as _stall_dsn_fixture,
)
from tests.agent_storage.test_postgres_migrations import (
    postgres_dsn as _stall_postgres_fixture,
)

isolated_migration_dsn = _stall_dsn_fixture

postgres_dsn = _stall_postgres_fixture


class Publisher:
    def __init__(self, call=lambda: None):
        self.call, self.closed = call, 0

    def publish_frontier(self, **kwargs):
        return self.call()

    def close(self):
        self.closed += 1


def sample():
    return StreamHintClaim("ns", SessionId(uuid4()), "owner", 1, 0, datetime.now(UTC))


def test_publish_failure_settles_pending_and_one_deadline(monkeypatch):
    deadlines, confirmed = [], []

    def claim(*args, **kwargs):
        deadlines.append(current_task_io_deadline())
        return (sample(),)

    def publish():
        deadlines.append(current_redis_io_deadline())
        raise ConnectionError("safe synthetic transport failure")

    def settle(*args, **kwargs):
        deadlines.append(current_task_io_deadline())
        confirmed.append(kwargs["confirmed"])
        return True

    monkeypatch.setattr(runtime, "claim_stream_hints", claim)
    monkeypatch.setattr(runtime, "settle_stream_hint", settle)
    publisher = Publisher(publish)
    relay = runtime.StreamHintRelay("test", "ns", publisher)
    with task_io_deadline(monotonic() + 0.5):
        assert relay.tick() == 0
    assert confirmed == [False] and len(set(deadlines)) == 1
    relay.close()
    relay.close()
    assert relay.tick() == 0 and publisher.closed == 1


def test_no_settle_when_publish_spent_remaining_budget(monkeypatch):
    monkeypatch.setattr(runtime, "claim_stream_hints", lambda *a, **k: (sample(), sample()))
    monkeypatch.setattr(runtime, "settle_stream_hint", lambda *a, **k: pytest.fail("late settle"))
    relay = runtime.StreamHintRelay("test", "ns", Publisher(lambda: sleep(0.09)))
    with pytest.raises(TimeoutError), task_io_deadline(monotonic() + 0.08):
        relay.tick()
    relay.close()


def test_overlap_and_drain_close_only_after_active_tick(monkeypatch):
    entered, release = Event(), Event()

    def claim(*args, **kwargs):
        entered.set()
        assert release.wait(1)
        return ()

    monkeypatch.setattr(runtime, "claim_stream_hints", claim)
    publisher = Publisher()
    relay = runtime.StreamHintRelay("test", "ns", publisher)
    thread = Thread(target=relay.tick)
    thread.start()
    assert entered.wait(1)
    assert relay.tick() == 0
    closer = Thread(target=relay.close)
    closer.start()
    assert publisher.closed == 0
    release.set()
    thread.join(1)
    closer.join(1)
    assert not thread.is_alive() and not closer.is_alive() and publisher.closed == 1


def test_unknown_cancellation_leaves_claim_reclaimable(monkeypatch):
    class Cancelled(BaseException):
        pass

    def cancel():
        raise Cancelled()

    monkeypatch.setattr(runtime, "claim_stream_hints", lambda *a, **k: (sample(),))
    monkeypatch.setattr(
        runtime, "settle_stream_hint", lambda *a, **k: pytest.fail("cancelled settle")
    )
    relay = runtime.StreamHintRelay("test", "ns", Publisher(cancel))
    with pytest.raises(Cancelled):
        relay.tick()
    relay.close()
    assert relay.publisher.closed == 1


def test_exclusive_socket_timeouts_restore_and_tls_class_is_preserved(monkeypatch):
    from agent_integrations.redis_live_fanout import RedisLiveEventFanout
    from agent_integrations.redis_transient_deadlines import (
        TransientRedisConnection,
        TransientSSLRedisConnection,
        redis_io_deadline,
    )
    from redis.connection import Connection
    from redis.exceptions import TimeoutError as RedisTimeoutError

    clips = []
    connection = TransientRedisConnection(socket_timeout=4, socket_connect_timeout=3)

    def connect(self):
        clips.append((self.socket_connect_timeout, self.socket_timeout))
        raise RedisTimeoutError("safe synthetic connect failure")

    monkeypatch.setattr(Connection, "connect", connect)
    with redis_io_deadline(monotonic() + 0.2), pytest.raises(RedisTimeoutError):
        connection.connect()
    assert clips[0][0] <= 0.2 and clips[0][1] <= 0.2
    assert connection.socket_timeout == 4 and connection.socket_connect_timeout == 3
    assert current_redis_io_deadline() is None
    fanout = RedisLiveEventFanout.from_url("rediss://localhost:32782?ssl_cert_reqs=required")
    assert fanout._client.connection_pool.connection_class is TransientSSLRedisConnection
    assert fanout._client.connection_pool.connection_kwargs["ssl_cert_reqs"] == "required"
    fanout.close()


def test_pg_and_redis_share_shorter_output_and_redis_parent(monkeypatch):
    from contextlib import contextmanager, nullcontext
    from threading import RLock

    from agent_core.harness.public_output_lifecycle import public_output_lock
    from agent_integrations.redis_transient_deadlines import redis_io_deadline

    observed = []

    def claim(*args, **kwargs):
        observed.append(current_task_io_deadline())
        return (sample(),)

    def publish():
        observed.append(current_redis_io_deadline())

    def settle(*args, **kwargs):
        observed.append(current_task_io_deadline())
        return True

    monkeypatch.setattr(runtime, "claim_stream_hints", claim)
    monkeypatch.setattr(runtime, "settle_stream_hint", settle)

    @contextmanager
    def output_scope(deadline):
        yield min(deadline, public_deadline)

    relay = runtime.StreamHintRelay("test", "ns", Publisher(publish))
    for public in (False, True):
        observed.clear()
        public_deadline = monotonic() + 0.2
        parent = monotonic() + 0.3
        with task_io_deadline(monotonic() + 0.5), redis_io_deadline(parent):
            with public_output_lock(RLock(), output_scope) if public else nullcontext():
                assert relay.tick() == 1
        expected = public_deadline if public else parent
        assert observed == [expected] * 3
    relay.close()


class _ReplyProxy:
    """One owned loopback relay client; never pauses the shared Redis server."""

    def __init__(self, url):
        import socket
        from urllib.parse import urlsplit, urlunsplit

        source = urlsplit(url)
        assert source.hostname in {"127.0.0.1", "localhost"} and source.port == 32782
        self.upstream = (source.hostname, source.port)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.05)
        authority = source.netloc.rsplit("@", 1)[0] + "@" if "@" in source.netloc else ""
        self.url = urlunsplit(
            (
                source.scheme,
                authority + "127.0.0.1:" + str(self.listener.getsockname()[1]),
                source.path,
                source.query,
                "",
            )
        )
        self.stop, self.reply_seen = Event(), Event()
        self.reply_delay = 0
        self.peers, self.workers = [], []
        self.thread = Thread(target=self._accept)

    def _accept(self):
        while not self.stop.is_set():
            try:
                peer, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            worker = Thread(target=self._forward, args=(peer,))
            self.workers.append(worker)
            worker.start()

    def _forward(self, peer):
        import socket
        from select import select

        upstream = socket.create_connection(self.upstream, timeout=1)
        self.peers.extend((peer, upstream))
        try:
            while not self.stop.is_set():
                ready, _, _ = select([peer, upstream], [], [], 0.05)
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    if source is upstream and self.reply_delay:
                        delay, self.reply_delay = self.reply_delay, 0
                        self.reply_seen.set()
                        self.stop.wait(delay)
                    (peer if source is upstream else upstream).sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            peer.close()
            upstream.close()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.listener.close()
        for peer in self.peers:
            peer.close()
        self.thread.join(2)
        for worker in self.workers:
            worker.join(2)
        assert not self.thread.is_alive() and all(not w.is_alive() for w in self.workers)


def test_supplement_real_redis_then_pg_stall_one_budget(isolated_migration_dsn, monkeypatch):
    import os

    import psycopg
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_integrations.redis_live_fanout import RedisLiveEventFanout
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.events import PostgresEventStore
    from agent_storage.postgres.migration_runner import apply_postgres_migrations

    dsn, namespace, sid = isolated_migration_dsn, "stall-" + uuid4().hex, SessionId(uuid4())
    apply_postgres_migrations(dsn)
    PostgresEventStore(dsn, deployment_namespace=namespace).append(
        SessionEvent.create(
            session_id=sid,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "relay"},
        )
    )
    connections, blocker = [], psycopg.connect(dsn)
    connect = PostgresDatabase.connect_task_io

    def tracked(self, **kwargs):
        connection = connect(self, **kwargs)
        connections.append((connection, connection.info.backend_pid))
        return connection

    monkeypatch.setattr(PostgresDatabase, "connect_task_io", tracked)
    with _ReplyProxy(os.environ["ZEBRA_STREAM_TEST_REDIS_URL"]) as proxy:
        fanout = RedisLiveEventFanout.from_url(proxy.url)
        # Warm this exclusive relay transport outside the measured budget.
        fanout._client.ping()
        original = fanout.publish_frontier
        options = dict(fanout._client.connection_pool.connection_kwargs)

        def publish(**kwargs):
            proxy.reply_delay = 0.12
            result = original(
                **kwargs
            )  # Actual owned Redis Lua, response delayed on this client only.
            blocker.execute(
                "SELECT 1 FROM session_streams WHERE deployment_namespace=%s "
                "AND session_id=%s FOR UPDATE",
                (namespace, sid),
            )
            return result

        monkeypatch.setattr(fanout, "publish_frontier", publish)
        relay = runtime.StreamHintRelay(dsn, namespace, fanout)
        started = monotonic()
        try:
            try:
                with task_io_deadline(started + 0.35):
                    result = relay.tick()
            except TimeoutError:
                result = 0
            assert result == 0
            assert proxy.reply_seen.is_set() and monotonic() - started < 0.8
            assert len(connections) == 2 and all(c.closed for c, _ in connections)
            assert options == fanout._client.connection_pool.connection_kwargs
            assert fanout._client.xlen(fanout._stream_key(namespace, sid) + ":frontier") == 1
            with psycopg.connect(dsn) as observer:
                row = observer.execute(
                    "SELECT claim_owner,published_through,lease_expires_at "
                    "FROM session_streams WHERE deployment_namespace=%s",
                    (namespace,),
                ).fetchone()
                assert row[0] is not None and row[1] == -1 and row[2] is not None
                assert (
                    observer.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid=ANY(%s)",
                        ([pid for _, pid in connections],),
                    ).fetchone()[0]
                    == 0
                )
        finally:
            blocker.rollback()
            blocker.close()
            fanout._client.delete(fanout._stream_key(namespace, sid) + ":frontier")
            relay.close()
