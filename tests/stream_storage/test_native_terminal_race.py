"""Controlled native scheduling oracle for the v1 empty-read/terminal race.

The scheduling hook performs a real fenced commit after the real empty PG read.
No fake store counts qualify as native baseline. READ must reverse the last
assertion when it fixes the actual tail algorithm.
"""

import asyncio
import os
from pathlib import Path

import pytest
from agent_core.domain.events import EventType
from zebra_agent_api.session_streaming import tail_session_events

from tests.stream_storage.native_baseline import Request, write
from tests.stream_storage.native_environment import native_environment, seed


def test_native_empty_read_before_terminal_status_loses_terminal(monkeypatch):
    dsn = os.environ.get("ZEBRA_STREAM_TEST_POSTGRES_DSN")
    redis_url = os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL")
    if not dsn or not redis_url:
        pytest.skip("set private native stream dependencies")
    with native_environment(dsn, redis_url) as (scratch, _, fanout):
        run = seed(scratch, fanout, 1)
        read = run.stores.events.read_since
        committed = False

        def scheduled_read(session_id, sequence):
            nonlocal committed
            rows = read(session_id, sequence)
            if not rows and not committed:
                write(run, "terminal", 0)
                committed = True
            return rows

        monkeypatch.setattr(run.stores.events, "read_since", scheduled_read)

        async def collect():
            return [
                frame
                async for frame in tail_session_events(
                    database_path=Path("/unused"),
                    stores=run.stores,
                    session_id=run.session_id,
                    request=Request(),
                    after_sequence=0,
                )
            ]

        frames = asyncio.run(collect())
        assert committed
        assert run.stores.events.list_for_session(run.session_id)[-1].event_type is (
            EventType.SESSION_COMPLETED
        )
        assert not any("session_completed" in frame for frame in frames)
