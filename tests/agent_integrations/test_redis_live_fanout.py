from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.live_event_fanout import LiveEventCursor
from agent_integrations.redis_live_fanout import (
    RedisLiveEventError,
    RedisLiveEventFanout,
)
from redis.exceptions import ResponseError


class _FakeRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._next_id = 0
        self.fail_reads = False
        self.last_approximate: bool | None = None
        self.last_block: int | None = None

    def xadd(
        self,
        name: str,
        fields: Mapping[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        self.last_approximate = approximate
        self._next_id += 1
        cursor = f"{self._next_id}-0"
        entries = self.streams.setdefault(name, [])
        entries.append((cursor, dict(fields)))
        if maxlen is not None:
            del entries[:-maxlen]
        return cursor

    def xinfo_stream(self, name: str) -> Mapping[str, object]:
        if not self.streams.get(name):
            raise ResponseError("no such key")
        return {"last-generated-id": self.streams[name][-1][0]}

    def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> Sequence[tuple[str, Sequence[tuple[str, Mapping[str, str]]]]]:
        self.last_block = block
        if self.fail_reads:
            raise ConnectionError("redis unavailable")
        name, cursor = next(iter(streams.items()))
        minimum = int(cursor.split("-", 1)[0])
        entries = [
            entry
            for entry in self.streams.get(name, [])
            if int(entry[0].split("-", 1)[0]) > minimum
        ]
        if count is not None:
            entries = entries[:count]
        return [(name, entries)] if entries else []


def _event(session_id: SessionId, sequence: int) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.SESSION_CREATED if sequence == 1 else EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.SYSTEM,
        payload={"title": "live"} if sequence == 1 else {"content": f"message-{sequence}"},
    )


def _adapter(*, max_stream_length: int = 100) -> tuple[RedisLiveEventFanout, _FakeRedis]:
    client = _FakeRedis()
    return RedisLiveEventFanout(client, max_stream_length=max_stream_length), client


def test_replay_barrier_then_tail_returns_only_new_canonical_events() -> None:
    adapter, client = _adapter()
    session_id = SessionId(uuid4())
    barrier = adapter.capture_barrier(deployment_namespace="deployment-a", session_id=session_id)

    adapter.publish(deployment_namespace="deployment-a", event=_event(session_id, 1))
    adapter.publish(deployment_namespace="deployment-a", event=_event(session_id, 2))

    events = adapter.read_after(
        deployment_namespace="deployment-a",
        session_id=session_id,
        barrier=barrier,
        durable_sequence=1,
    )
    assert [event.event.sequence for event in events.events] == [2]
    assert events.events[0].deployment_namespace == "deployment-a"
    assert events.next_cursor.value == "2-0"
    assert client.last_block is None


@pytest.mark.parametrize("namespace", ["", " deployment-a", "deployment-a "])
def test_capture_barrier_rejects_invalid_namespace(namespace: str) -> None:
    adapter, _ = _adapter()

    with pytest.raises(ValueError, match="deployment_namespace"):
        adapter.capture_barrier(deployment_namespace=namespace, session_id=SessionId(uuid4()))


def test_positive_block_timeout_is_forwarded_to_redis() -> None:
    adapter, client = _adapter()
    session_id = SessionId(uuid4())

    adapter.read_after(
        deployment_namespace="deployment-a",
        session_id=session_id,
        barrier=LiveEventCursor("0-0"),
        durable_sequence=-1,
        block_ms=25,
    )

    assert client.last_block == 25


def test_namespace_isolation_and_duplicate_filtering() -> None:
    adapter, _ = _adapter()
    session_id = SessionId(uuid4())
    barrier = adapter.capture_barrier(deployment_namespace="deployment-a", session_id=session_id)
    event = _event(session_id, 1)
    adapter.publish(deployment_namespace="deployment-a", event=event)
    adapter.publish(deployment_namespace="deployment-a", event=event)

    assert adapter.read_after(
        deployment_namespace="deployment-b",
        session_id=session_id,
        barrier=LiveEventCursor("0-0"),
        durable_sequence=-1,
    ).events == ()
    events = adapter.read_after(
        deployment_namespace="deployment-a",
        session_id=session_id,
        barrier=barrier,
        durable_sequence=-1,
    )
    assert [item.event.event_id for item in events.events] == [event.event_id]


def test_filtered_replay_entries_still_advance_the_tail_cursor() -> None:
    adapter, _ = _adapter()
    session_id = SessionId(uuid4())
    barrier = LiveEventCursor("0-0")
    adapter.publish(deployment_namespace="deployment-a", event=_event(session_id, 1))
    adapter.publish(deployment_namespace="deployment-a", event=_event(session_id, 2))

    first = adapter.read_after(
        deployment_namespace="deployment-a",
        session_id=session_id,
        barrier=barrier,
        durable_sequence=1,
        count=1,
    )
    assert first.events == ()
    assert first.next_cursor.value == "1-0"
    second = adapter.read_after(
        deployment_namespace="deployment-a",
        session_id=session_id,
        barrier=first.next_cursor,
        durable_sequence=1,
        count=1,
    )
    assert [item.event.sequence for item in second.events] == [2]


def test_barrier_cannot_be_reused_for_another_namespace() -> None:
    adapter, _ = _adapter()
    session_id = SessionId(uuid4())
    barrier = adapter.capture_barrier(deployment_namespace="deployment-a", session_id=session_id)

    with pytest.raises(RedisLiveEventError, match="barrier"):
        adapter.read_after(
            deployment_namespace="deployment-b",
            session_id=session_id,
            barrier=barrier,
            durable_sequence=-1,
        )


def test_bounded_stream_drops_old_live_entries() -> None:
    adapter, client = _adapter(max_stream_length=2)
    session_id = SessionId(uuid4())
    barrier = LiveEventCursor("0-0")
    for sequence in range(1, 4):
        adapter.publish(deployment_namespace="deployment-a", event=_event(session_id, sequence))

    events = adapter.read_after(
        deployment_namespace="deployment-a",
        session_id=session_id,
        barrier=barrier,
        durable_sequence=-1,
    )
    assert [event.event.sequence for event in events.events] == [2, 3]
    assert events.next_cursor.value == "3-0"
    assert client.last_approximate is False


def test_malformed_metadata_is_rejected() -> None:
    adapter, client = _adapter()
    session_id = SessionId(uuid4())
    adapter.publish(deployment_namespace="deployment-a", event=_event(session_id, 1))
    key = next(iter(client.streams))
    client.streams[key][0][1]["namespace"] = "deployment-b"

    with pytest.raises(RedisLiveEventError, match="namespace"):
        adapter.read_after(
            deployment_namespace="deployment-a",
            session_id=session_id,
            barrier=LiveEventCursor("0-0"),
            durable_sequence=-1,
        )


def test_redis_failures_are_not_silently_converted_to_empty_tail() -> None:
    adapter, client = _adapter()
    client.fail_reads = True

    with pytest.raises(ConnectionError, match="unavailable"):
        adapter.read_after(
            deployment_namespace="deployment-a",
            session_id=SessionId(uuid4()),
            barrier=LiveEventCursor("0-0"),
            durable_sequence=-1,
        )


@pytest.mark.parametrize("kwargs", [{"max_stream_length": 0}, {"key_prefix": "bad prefix"}])
def test_adapter_rejects_invalid_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RedisLiveEventFanout(_FakeRedis(), **kwargs)  # type: ignore[arg-type]
