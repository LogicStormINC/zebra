"""Raw SSE durability when the Redis notification channel is unavailable."""

import asyncio
from pathlib import Path

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from zebra_agent_api.session_streaming import tail_session_events, tail_task_events

from tests.api.test_cloud_stream_read_bounds import append
from tests.api.test_cloud_stream_read_bounds import postgres_dsn as _dsn_fixture
from tests.api.test_cloud_stream_read_bounds import source as _source_fixture
from tests.api.test_cloud_stream_read_bounds import task_namespace as _namespace_fixture

postgres_dsn = _dsn_fixture
source = _source_fixture
task_namespace = _namespace_fixture


class Connected:
    async def is_disconnected(self):
        return False


@pytest.mark.parametrize("reader", ["session", "task"])
def test_redis_loss_reads_committed_suffix_without_waiting_for_redis_retry(
    source, monkeypatch, reader
):
    import json

    from zebra_agent_api import session_streaming

    stores, sid = source
    append(source, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    cursor = stores.tasks.read_stream_source_head(task_id=TaskId(sid)).task.current_sequence
    now, commit_at = 0.0, 18.0
    committed = []
    redis_attempts = []

    class LostRedis:
        key = staticmethod(lambda *args, **kwargs: "test-key")

        async def barrier(self, key):
            redis_attempts.append(now)
            if now:
                raise ConnectionError("Redis remains down")
            return "0-0"

        async def wait(self, *args, **kwargs):
            raise ConnectionError("existing Redis connection closed")

    async def sleep_until(deadline, retry_at, keepalive):
        nonlocal now
        if not committed and retry_at >= commit_at:
            committed.extend(
                [
                    append(source, EventType.MODEL_RESPONSE_DELTA, {"content_delta": "one"}),
                    append(
                        source, EventType.SESSION_COMPLETED, {"summary": "done", "metadata": {}}
                    ),
                ]
            )
        now = retry_at
        return True

    monkeypatch.setattr(session_streaming, "monotonic", lambda: now)
    monkeypatch.setattr(session_streaming, "uniform", lambda a, b: 1.1)
    monkeypatch.setattr(session_streaming, "_backoff_slice", sleep_until)
    tail = tail_session_events if reader == "session" else tail_task_events

    async def collect():
        frames = [
            frame
            async for frame in tail(
                database_path=Path("/unused"),
                stores=stores,
                request=Connected(),
                after_sequence=cursor,
                live_event_fanout=object(),
                deployment_namespace=stores.deployment_namespace,
                notifications=LostRedis(),
                **({"session_id": sid} if reader == "session" else {"task_id": TaskId(sid)}),
            )
            if frame.startswith("id:")
        ]
        return [json.loads(frame.split("data: ", 1)[1]) for frame in frames]

    async def check():
        existing = await collect()
        assert now - commit_at <= 5
        assert len(redis_attempts) < 8
        reconnect = await collect()
        expected = [(cursor + i, str(event.event_id)) for i, event in enumerate(committed, 1)]
        for events in (existing, reconnect):
            assert [(event["sequence"], event["event_id"]) for event in events] == expected

    asyncio.run(asyncio.wait_for(check(), 10))


def test_cancelled_raw_stream_releases_redis_wait(source):
    stores, sid = source
    append(source, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    cursor = stores.tasks.read_stream_source_head(task_id=TaskId(sid)).task.current_sequence

    async def check():
        waiting = asyncio.Event()
        released = asyncio.Event()

        class BlockingRedis:
            key = staticmethod(lambda *args, **kwargs: "test-key")

            async def barrier(self, key):
                return "0-0"

            async def wait(self, *args, **kwargs):
                try:
                    waiting.set()
                    await asyncio.Future()
                finally:
                    released.set()

        stream = tail_task_events(
            database_path=Path("/unused"),
            stores=stores,
            request=Connected(),
            after_sequence=cursor,
            live_event_fanout=object(),
            deployment_namespace=stores.deployment_namespace,
            notifications=BlockingRedis(),
            task_id=TaskId(sid),
        )
        pending = asyncio.create_task(anext(stream))
        try:
            await asyncio.wait_for(waiting.wait(), 3)
        finally:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await stream.aclose()
        assert released.is_set()

    asyncio.run(check())
