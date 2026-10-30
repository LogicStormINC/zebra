"""Probe backpressure cannot block the real execution/control loop."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock

from zebra_agent_worker.runtime_gates import RuntimeGateWorker


def test_one_background_probe_keeps_slot_until_actual_io_finishes():
    worker = object.__new__(RuntimeGateWorker)
    worker.pid = os.getpid()
    worker.next_tick = 0
    worker._closed = False
    worker._future = None
    from threading import Lock

    worker._lock = Lock()
    worker._executor = ThreadPoolExecutor(1)
    entered, release = Event(), Event()

    def observe():
        entered.set()
        release.wait(3)

    worker._observe = observe
    worker.store = MagicMock()
    worker.process = "owned-test"
    try:
        worker.tick()
        assert entered.wait(1)
        original = worker._future
        worker.next_tick = 0
        worker.tick()
        assert worker._future is original and not original.done()
    finally:
        release.set()
        worker.close()
    worker.next_tick = 0
    worker.tick()
    worker.store.close.assert_called_once_with("owned-test")


def test_inherited_observer_never_attests_or_revokes_parent():
    worker = object.__new__(RuntimeGateWorker)
    worker.pid = os.getpid() + 1
    worker.store = MagicMock()
    worker.tick()
    worker.close()
    assert not worker.store.mock_calls
