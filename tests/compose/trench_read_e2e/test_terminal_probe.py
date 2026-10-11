"""QA observation guards; these tests are not real terminal acceptance."""

from __future__ import annotations

import json
import threading
import time
from types import FunctionType

import pytest


def test_cleanup_rejects_answer_without_native_release_or_live_probe():
    from terminal_probe import terminal_clean

    native = {"final_count": 1, "status": "completed", "lease_released": True}
    idle = {
        "schema_version": "zebra.qa-worker-observation.v1",
        "coverage_complete": True,
        "execution_threads": 0,
        "model_threads": 0,
        "public_wait_timers": 0,
        "text_flush_timers": 0,
        "lease_heartbeat_threads": 0,
    }
    assert terminal_clean(native, idle)
    for key, value in (("final_count", 2), ("status", "running"), ("lease_released", False)):
        assert not terminal_clean({**native, key: value}, idle)
    assert not terminal_clean(native, {})
    assert not terminal_clean(native, {**idle, "coverage_complete": False})
    for key in idle.keys() - {"schema_version", "coverage_complete"}:
        assert not terminal_clean(native, {**idle, key: 1})
        assert not terminal_clean(native, {**idle, key: False})


@pytest.mark.parametrize(
    "module,key",
    [
        ("agent_core.harness.public_output", "public_wait_timers"),
        ("agent_core.harness.stream_deltas", "text_flush_timers"),
    ],
)
def test_live_cancelled_timer_is_counted_until_thread_has_exited(module, key):
    from worker_observation import observe

    callback = FunctionType((lambda: None).__code__, {"__name__": module})
    timer = threading.Timer(30, callback)
    timer.start()
    try:
        sample = observe()
        assert sample[key] == 1
        assert sample["coverage_complete"] is True
        assert "__name__" not in json.dumps(sample)
    finally:
        timer.cancel()
        timer.join(timeout=1)
    assert not timer.is_alive()
    assert observe()[key] == 0


def test_live_model_frame_counted_without_exporting_locals():
    from worker_observation import observe

    started, stop = threading.Event(), threading.Event()

    def complete_stream():
        started.set()
        stop.wait(2)

    function = FunctionType(
        complete_stream.__code__,
        {"__name__": "agent_integrations.openai_compatible"},
        closure=complete_stream.__closure__,
    )
    thread = threading.Thread(target=function)
    thread.start()
    assert started.wait(1)
    try:
        sample = observe()
        assert sample["model_threads"] == 1
        assert "stop" not in json.dumps(sample)
    finally:
        stop.set()
        thread.join(timeout=1)
    assert observe()["model_threads"] == 0


def test_cleanup_budget_starts_at_answer_not_at_probe_launch():
    from terminal_probe import cleanup_deadline

    answered = time.monotonic() - 6
    with pytest.raises(TimeoutError):
        cleanup_deadline(answered, 5)
    assert cleanup_deadline(time.monotonic(), 5) <= time.monotonic() + 5
