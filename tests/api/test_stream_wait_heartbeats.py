"""Deterministic clock checks; heartbeat slices must not become SQL/Redis retries."""

import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest
from agent_core.ports.live_event_fanout import LiveEventBatch, LiveEventCursor
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from zebra_agent_api import ag_ui_checkpoint_tail as checkpoint
from zebra_agent_api import session_streaming as session

from tests.api.test_live_session_streaming import _seed_session


class Clock:
    now = 0.0

    async def sleep(self, seconds):
        self.now += seconds


class Fanout:
    def __init__(self, clock, outage):
        self.clock, self.outage = clock, outage
        self.captures, self.waits = 0, 0

    def capture_barrier(self, **kwargs):
        self.captures += 1
        if self.outage:
            raise ConnectionError("offline")
        return LiveEventCursor("0-0")

    capture_checkpoint_barrier = capture_barrier

    def read_after(self, **kwargs):
        self.waits += 1
        self.clock.now += 1
        return LiveEventBatch((), kwargs["barrier"])

    def wait_checkpoint_after(self, **kwargs):
        return self.read_after(**kwargs).next_cursor

    def publish_checkpoint(self, head):
        raise AssertionError("an observer must never publish")


class Connected:
    async def is_disconnected(self):
        return False


@pytest.mark.parametrize("reader, heartbeat", [("session", 15), ("agui", 3)])
@pytest.mark.parametrize("outage", [False, True])
def test_heartbeats_continue_without_advancing_thirty_second_sql_retry(
    tmp_path, monkeypatch, reader, heartbeat, outage
):
    clock, reads = Clock(), []
    fanout = Fanout(clock, outage)
    for module in (checkpoint, session):
        monkeypatch.setattr(module, "monotonic", lambda: clock.now)
        monkeypatch.setattr(module, "uniform", lambda *args: 1)
    monkeypatch.setattr(checkpoint.asyncio, "sleep", clock.sleep)

    async def read(deadline, operation, *args, **kwargs):
        reads.append(operation.__name__)
        return operation(*args, **kwargs)

    monkeypatch.setattr(checkpoint, "_read_until", read)
    monkeypatch.setattr(session, "_read_until", read)
    if reader == "session":
        database, identity, revision = _seed_session(tmp_path)
        init = session.StreamWake.__init__

        def capped(self, *args, **kwargs):
            init(self, *args, **kwargs)
            self.backoff = 30

        monkeypatch.setattr(session.StreamWake, "__init__", capped)
        source = session.tail_session_events(
            database_path=database, session_id=identity, request=Connected(),
            after_sequence=revision, live_event_fanout=fanout, deployment_namespace="cloud",
        )
        replay_name = "read_since"
    else:
        def snapshot(*args):
            raise CheckpointNotReady("background projection pending")

        monkeypatch.setattr(checkpoint.AgUiCheckpointObserver, "snapshot", snapshot)
        wait = checkpoint._checkpoint_wait

        async def capped_wait(context, deadline, barrier, poll, backoff, keepalive, retry_at):
            return await wait(context, deadline, barrier, poll, 30, keepalive, retry_at)

        monkeypatch.setattr(checkpoint, "_checkpoint_wait", capped_wait)
        context = SimpleNamespace(
            stores=SimpleNamespace(tasks=None), deployment_namespace="cloud",
            live_event_fanout=fanout, task_id=None, identity=None, cursor=None,
        )
        source = checkpoint.tail_checkpoint_frames(
            context, Connected(), 100, poll_seconds=0.25, keepalive_seconds=heartbeat,
        )
        replay_name = "snapshot"

    async def collect():
        async with aclosing(source):
            for stamp in range(heartbeat, 30, heartbeat):
                assert await anext(source) == ": keepalive\n\n"
                assert clock.now == stamp
                assert reads.count(replay_name) == 1
                assert fanout.captures == 1
            assert await anext(source) == ": keepalive\n\n"
            assert clock.now == 30
            assert reads.count(replay_name) == 2
            assert fanout.captures == (2 if reader == "agui" and outage else 1)

    asyncio.run(collect())
