"""A cancelled measurement cannot drop its database while a writer still commits."""

import asyncio
from threading import Event

import pytest

from tests.stream_storage.native_baseline import native_mutations


def test_cancelled_native_mutation_waiter_drains_the_real_thread():
    started, release, committed = Event(), Event(), Event()

    def write():
        started.set()
        assert release.wait(5)
        committed.set()

    async def check():
        task = asyncio.create_task(native_mutations(write, [()]))
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not committed.is_set()
        # A repeated cancellation must still wait for the native writer, too.
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert committed.is_set()

    asyncio.run(check())
