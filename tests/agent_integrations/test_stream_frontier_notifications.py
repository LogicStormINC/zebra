"""Frontier hints use a separate wire, never a full-Event parser or authority."""

import asyncio
import os
from time import monotonic
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import SessionId
from agent_core.ports.live_event_fanout import LiveEventCursor
from agent_integrations.redis_live_fanout import RedisLiveEventError, RedisLiveEventFanout
from agent_integrations.redis_live_fanout_async import AsyncRedisNotifications
from zebra_agent_api.session_streaming import StreamWake

from tests.agent_integrations.test_redis_live_fanout import _adapter, _event


def test_native_atomic_ttl_trim_distinct_wire_and_legacy_reader():
    url = os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL")
    if not url:
        pytest.skip("owned Redis fixture not configured")
    namespace, sid = "relay-" + uuid4().hex, SessionId(uuid4())
    fanout = RedisLiveEventFanout.from_url(url, max_stream_length=2)
    old = fanout.capture_barrier(deployment_namespace=namespace, session_id=sid)
    frontier = fanout.capture_frontier_barrier(deployment_namespace=namespace, session_id=sid)
    try:
        for through in (0, 0, 1):
            fanout.publish_frontier(deployment_namespace=namespace, session_id=sid, through=through)
        current = fanout.wait_frontier_after(
            deployment_namespace=namespace, session_id=sid, barrier=frontier, block_ms=1
        )
        assert current != frontier and current.stream_ref != old.stream_ref
        client = fanout._client
        assert client.xlen(current.stream_ref) == 2 and 0 < client.ttl(current.stream_ref) <= 300
        assert (
            fanout.read_after(
                deployment_namespace=namespace, session_id=sid, barrier=old, durable_sequence=-1
            ).events
            == ()
        )
        fanout.publish(deployment_namespace=namespace, event=_event(sid, 1))
        assert (
            len(
                fanout.read_after(
                    deployment_namespace=namespace, session_id=sid, barrier=old, durable_sequence=-1
                ).events
            )
            == 1
        )
        client.xadd(current.stream_ref, {"namespace": "foreign", "event": "forbidden body"})
        with pytest.raises(RedisLiveEventError):
            fanout.wait_frontier_after(
                deployment_namespace=namespace, session_id=sid, barrier=current, block_ms=1
            )
    finally:
        fanout._client.delete(old.stream_ref, frontier.stream_ref)
        fanout.close()


def test_raw_cloud_frontier_selection_and_custom_legacy_fallback():
    class Frontier:
        def capture_barrier(self, **kw):
            raise AssertionError("wrong full-Event key")

        def publish(self, **kw):
            raise AssertionError("unexpected Event publication")

        def read_after(self, **kw):
            raise AssertionError("full-Event body parser")

        def capture_frontier_barrier(self, **kw):
            return LiveEventCursor("0-0", stream_ref="frontier")

        def publish_frontier(self, **kw):
            return LiveEventCursor("1-0", stream_ref="frontier")

        def wait_frontier_after(self, **kw):
            return LiveEventCursor("1-0", stream_ref="frontier")

    async def check():
        sid = SessionId(uuid4())
        wake = StreamWake(Frontier(), "ns", sid, monotonic() + 1, cloud=True)
        await wake.capture()
        assert await wake.wait(-1) and wake.cursor.stream_ref == "frontier"
        legacy, _ = _adapter()
        # Native fanout has the optional port; local preserves full-Event key.
        local = StreamWake(legacy, "local", sid, monotonic() + 1)
        await local.capture()
        assert not local.frontier and not local.cursor.stream_ref.endswith(":frontier")

    asyncio.run(check())


def test_async_key_replacement_preserves_four_key_bound():
    async def check():
        notifications = AsyncRedisNotifications("redis://localhost:32782")
        try:
            canonical = notifications.key("ns", "session", frontier=True)
            assert canonical.endswith(":frontier")
            positions = {
                canonical: "0-0",
                notifications.key("ns", "task", checkpoint=True): "0-0",
                "control": "0-0",
                "generation": "0-0",
            }

            async def xread(streams, **kwargs):
                assert len(streams) == 4 and canonical in streams
                return [(canonical, [("1-0", {})])]

            notifications.client.xread = xread
            assert (await notifications.wait(positions))[canonical] == "1-0"
            with pytest.raises(ValueError):
                await notifications.wait({**positions, "fifth": "0-0"})
            with pytest.raises(ValueError):
                notifications.key("ns", "session", frontier=True, checkpoint=True)
        finally:
            await notifications.close()

    asyncio.run(check())


@pytest.mark.parametrize("scheme", ["redis", "rediss", "unix"])
@pytest.mark.parametrize("factory", ["fanout", "transient"])
def test_transport_factory_preserves_native_url_options_and_deadline(
    tmp_path, monkeypatch, scheme, factory
):
    from time import monotonic

    from agent_integrations.redis_transient_deadlines import (
        TransientRedisConnection,
        TransientSSLRedisConnection,
        TransientUnixRedisConnection,
        redis_io_deadline,
    )
    from agent_integrations.redis_transient_output import RedisTransientOutput
    from redis.connection import AbstractConnection
    from redis.exceptions import TimeoutError as RedisTimeoutError

    path = tmp_path / "redis endpoint.sock"
    from urllib.parse import quote

    endpoint = quote(str(path)) if scheme == "unix" else "localhost:32782/3"
    url = f"{scheme}://demo:example@{endpoint}?db=3&socket_timeout=0.7"
    if scheme == "rediss":
        url += "&ssl_cert_reqs=required"
    adapter = (
        RedisLiveEventFanout.from_url(url)
        if factory == "fanout"
        else RedisTransientOutput.from_url(url, resolve_authorization=lambda _: None)
    )
    client = adapter._client
    pool = client.connection_pool
    expected = {
        "redis": TransientRedisConnection,
        "rediss": TransientSSLRedisConnection,
        "unix": TransientUnixRedisConnection,
    }[scheme]
    assert pool.connection_class is expected
    connection = pool.connection_class(**pool.connection_kwargs)
    assert connection.username == "demo" and connection.password == "example" and connection.db == 3
    assert connection.socket_timeout == 0.7
    if scheme == "unix":
        assert connection.path == str(path)
    if scheme == "rediss":
        assert pool.connection_kwargs["ssl_cert_reqs"] == "required"
    seen = []

    def connect(self):
        seen.append((self.socket_connect_timeout, self.socket_timeout))
        raise RedisTimeoutError("synthetic constructor-only connection check")

    monkeypatch.setattr(AbstractConnection, "connect", connect)
    before = connection.socket_connect_timeout, connection.socket_timeout
    with redis_io_deadline(monotonic() + 0.05), pytest.raises(RedisTimeoutError):
        connection.connect()
    assert seen and all(0 < value <= 0.05 for value in seen[0])
    assert before == (connection.socket_connect_timeout, connection.socket_timeout)
    client.close()
    pool.disconnect()
    if factory == "fanout":
        adapter.close()


def test_native_unix_socket_via_owned_redis_bridge_and_timeout(tmp_path):
    import socket
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from urllib.parse import quote, urlsplit

    from agent_integrations.redis_transient_deadlines import (
        TransientUnixRedisConnection,
        redis_io_deadline,
    )
    from agent_integrations.redis_transient_output import RedisTransientOutput
    from redis.exceptions import TimeoutError as RedisTimeoutError

    from tests.agent_runtime.test_stream_hint_relay import _ReplyProxy

    configured = os.environ["ZEBRA_STREAM_TEST_REDIS_URL"]
    proxy = _ReplyProxy(configured)
    proxy.listener.close()
    with TemporaryDirectory(prefix="relay-unix-", dir="/tmp") as directory:
        path = Path(directory) / "native-redis.sock"
        proxy.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        proxy.listener.bind(str(path))
        proxy.listener.listen()
        proxy.listener.settimeout(0.05)
        parsed = urlsplit(configured)
        auth = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
        proxy.url = "unix://" + auth + quote(str(path)) + "?db=0"
        namespace, sid = "unix-" + uuid4().hex, SessionId(uuid4())
        with proxy:
            fanout = RedisLiveEventFanout.from_url(proxy.url)
            writer = RedisTransientOutput.from_url(proxy.url, resolve_authorization=lambda _: None)
            try:
                assert writer._client.ping()
                assert (
                    writer._client.connection_pool.connection_class is TransientUnixRedisConnection
                )
                barrier = fanout.capture_frontier_barrier(
                    deployment_namespace=namespace, session_id=sid
                )
                fanout.publish_frontier(deployment_namespace=namespace, session_id=sid, through=0)
                assert (
                    fanout.wait_frontier_after(
                        deployment_namespace=namespace, session_id=sid, barrier=barrier, block_ms=1
                    )
                    != barrier
                )
                proxy.reply_delay = 0.12
                started = monotonic()
                with redis_io_deadline(started + 0.03), pytest.raises(RedisTimeoutError):
                    writer._client.ping()
                assert proxy.reply_seen.wait(1) and monotonic() - started < 0.5
                assert (
                    writer._client.ping()
                )  # Exclusive socket can reconnect with restored options.
            finally:
                fanout._client.delete(fanout._stream_key(namespace, sid) + ":frontier")
                writer._client.close()
                writer._client.connection_pool.disconnect()
                fanout.close()
