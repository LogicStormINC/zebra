"""Controlled native scheduling oracle for the v1 empty-read/terminal race.

The scheduling hook performs a real fenced commit after the real empty PG read.
Both reader algorithms must drain the terminal commit after observing its status.
"""

import asyncio
import os
from pathlib import Path

import pytest
from agent_core.domain.events import EventType
from zebra_agent_api.session_streaming import tail_session_events, tail_task_events

from tests.stream_storage.native_baseline import Request, write
from tests.stream_storage.native_environment import native_environment, seed


@pytest.mark.parametrize("reader", ["session", "task"])
def test_native_empty_read_before_terminal_status_preserves_terminal(monkeypatch, reader):
    dsn = os.environ.get("ZEBRA_STREAM_TEST_POSTGRES_DSN")
    redis_url = os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL")
    if not dsn or not redis_url:
        pytest.skip("set private native stream dependencies")
    with native_environment(dsn, redis_url) as (scratch, _, fanout):
        run = seed(scratch, fanout, 1)
        owner = run.stores.events if reader == "session" else run.stores.tasks
        method = "read_since" if reader == "session" else "read_event_page"
        read = getattr(owner, method)
        committed = False

        def scheduled_read(session_id, sequence, **kwargs):
            nonlocal committed
            rows = read(session_id, sequence, **kwargs)
            empty = not rows if reader == "session" else not rows.events
            if empty and not committed:
                committed = True
                write(run, "terminal", 0)
            return rows

        monkeypatch.setattr(owner, method, scheduled_read)

        tail = tail_session_events if reader == "session" else tail_task_events

        async def collect():
            return [
                frame
                async for frame in tail(
                    database_path=Path("/unused"),
                    stores=run.stores,
                    **({"session_id": run.session_id} if reader == "session"
                       else {"task_id": run.task_id}),
                    request=Request(),
                    after_sequence=0,
                )
            ]

        frames = asyncio.run(collect())
        assert committed
        assert run.stores.events.list_for_session(run.session_id)[-1].event_type is (
            EventType.SESSION_COMPLETED
        )
        assert any("session_completed" in frame for frame in frames)
