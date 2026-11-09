"""Deterministic clock checks; heartbeat slices must not become SQL/Redis retries."""

import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.live_event_fanout import LiveEventBatch, LiveEventCursor
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_storage import SQLiteAgentTaskStore, SQLiteProjectionStore
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


def test_observation_retries_capacity_without_changing_read_coordinates(monkeypatch):
    from time import monotonic
    from unittest.mock import AsyncMock

    from agent_storage.postgres.connection_capacity import DatabaseCapacityExceeded

    read = object()
    expected_page = object()
    dispatch = AsyncMock(side_effect=[DatabaseCapacityExceeded(), expected_page])
    monkeypatch.setattr(checkpoint, "database_call", dispatch)
    monkeypatch.setattr(checkpoint, "uniform", lambda *_: 0)
    result = asyncio.run(checkpoint._read_until(monotonic() + 1, read, "task", 42))
    assert result is expected_page
    assert dispatch.await_count == 2
    assert dispatch.await_args_list[0] == dispatch.await_args_list[1]


def test_observation_capacity_backoff_stops_at_deadline(monkeypatch):
    from time import monotonic
    from unittest.mock import AsyncMock

    from agent_storage.postgres.connection_capacity import DatabaseCapacityExceeded

    dispatch = AsyncMock(side_effect=DatabaseCapacityExceeded())
    monkeypatch.setattr(checkpoint, "database_call", dispatch)
    monkeypatch.setattr(checkpoint, "uniform", lambda *_: 1)
    with pytest.raises(TimeoutError):
        asyncio.run(checkpoint._read_until(monotonic() + 0.1, lambda: None))
    assert dispatch.await_count == 1


@pytest.mark.parametrize("kind", ["task_id", "session_id"])
def test_raw_source_head_waits_for_projection_without_changing_target(monkeypatch, kind):
    from time import monotonic
    from unittest.mock import AsyncMock

    head = object()
    store = SimpleNamespace(read_stream_source_head=lambda **_: head)
    read = AsyncMock(side_effect=[CheckpointNotReady("source is ahead"), head])
    monkeypatch.setattr(session, "_read_until", read)
    monkeypatch.setattr(session, "uniform", lambda *_: 0)
    assert asyncio.run(session._read_raw_head(monotonic() + 1, store, **{kind: "target"})) is head
    assert read.await_count == 2
    assert read.await_args_list[0] == read.await_args_list[1]
    assert read.await_args.kwargs[kind] == "target"


@pytest.mark.parametrize("resource", ["session", "task"])
def test_native_stream_keeps_observing_during_approval(tmp_path, monkeypatch, resource):
    clock = Clock()
    database, identity, revision = _seed_session(tmp_path)
    projections = SQLiteProjectionStore(database)
    current = projections.get_session(identity)
    assert current is not None
    projections.save_session(current.model_copy(update={"status": SessionStatus.WAITING_APPROVAL}))
    monkeypatch.setattr(session, "monotonic", lambda: clock.now)

    async def wait(*args, **kwargs):
        clock.now += 15
        return False

    monkeypatch.setattr(session.StreamWake, "wait", wait)

    if resource == "task":
        task = SQLiteAgentTaskStore(database).ensure_for_session(identity)
        tail, target = session.tail_task_events, {"task_id": task.task_id}
    else:
        tail, target = session.tail_session_events, {"session_id": identity}

    async def collect():
        async with aclosing(tail(
            database_path=database, request=Connected(), after_sequence=revision, **target,
        )) as source:
            assert await anext(source) == ": keepalive\n\n"

    asyncio.run(asyncio.wait_for(collect(), 2))
