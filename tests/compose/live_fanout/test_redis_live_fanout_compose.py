from __future__ import annotations

import os
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_integrations.redis_live_fanout import RedisLiveEventError, RedisLiveEventFanout
from redis import Redis

_REDIS_URL = os.environ.get("ZEBRA_LIVE_REDIS_URL")

pytestmark = pytest.mark.skipif(
    not _REDIS_URL,
    reason="set ZEBRA_LIVE_REDIS_URL to run the real Redis Compose evidence",
)


def _event(session_id: SessionId, sequence: int) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.SESSION_CREATED if sequence == 1 else EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.SYSTEM,
        payload={"title": "compose-live"}
        if sequence == 1
        else {"content": f"compose-{sequence}"},
    )


def test_redis_stream_barrier_tail_and_namespace_isolation() -> None:
    assert _REDIS_URL is not None
    client = Redis.from_url(_REDIS_URL, decode_responses=True)
    client.flushdb()
    adapter = RedisLiveEventFanout(client, max_stream_length=2)
    session_id = SessionId(uuid4())
    barrier = adapter.capture_barrier(deployment_namespace="compose-a", session_id=session_id)
    adapter.publish(deployment_namespace="compose-a", event=_event(session_id, 1))
    adapter.publish(deployment_namespace="compose-a", event=_event(session_id, 2))
    adapter.publish(deployment_namespace="compose-a", event=_event(session_id, 3))

    try:
        events = adapter.read_after(
            deployment_namespace="compose-a",
            session_id=session_id,
            barrier=barrier,
            durable_sequence=1,
        )
        assert [item.event.sequence for item in events.events] == [2, 3]
        assert events.next_cursor.value
        with pytest.raises(RedisLiveEventError, match="barrier"):
            adapter.read_after(
                deployment_namespace="compose-b",
                session_id=session_id,
                barrier=barrier,
                durable_sequence=-1,
            )
    finally:
        client.flushdb()
        client.close()
