"""No business execution: prove polling bounds on the real Worker run paths."""

import asyncio
import math

import pytest
from zebra_agent_worker import worker_polling
from zebra_agent_worker.worker_loop_service import WorkerLoopCycleResult, WorkerLoopService

from tests.worker.test_command_process import _process

pytest_plugins = ["tests.worker.test_command_process"]


def test_cloud_blocked_loop_waits_and_progress_resets(monkeypatch):
    delays = []
    service = WorkerLoopService(None, None, sleep=delays.append, cloud_polling=True)
    blocked = WorkerLoopCycleResult(("ready",), (), ("ready",))
    progress = WorkerLoopCycleResult(("ready",), ("ready",), ())
    cycles = iter([blocked] * 5 + [progress, blocked])
    monkeypatch.setattr(service, "poll_once", lambda **kwargs: next(cycles))
    result = service.run(worker_id="worker", max_cycles=7, idle_sleep_seconds=0.1)
    assert result.cycles_completed == 7
    assert len(delays) == 6
    assert all(0.05 <= delay <= 1 for delay in delays)
    assert delays[4] > delays[0]
    assert delays[5] == 0.1


@pytest.mark.parametrize("state", ["idle", "blocked", "error"])
def test_backoff_is_bounded_even_after_long_outage(state):
    delay = worker_polling.PollingDelay(0)
    values = [delay.next(state) for _ in range(2000)]
    assert min(values) >= 0.05
    assert max(values) <= (5 if state == "error" else 1)
    assert values[-1] >= (4 if state == "error" else 0.8)
    assert delay.next("progress") == 0
    assert 0.05 <= delay.next("idle") <= 0.1


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -1, True])
def test_invalid_interval_rejected_before_poll(value):
    with pytest.raises(ValueError):
        worker_polling.validate_loop_inputs(
            batch_size=1, lease_ttl_seconds=30, max_cycles=1, idle_sleep_seconds=value
        )


def test_zero_interval_deferred_command_polling_cannot_spin(wired, monkeypatch):
    log, objects, *_ = wired
    process = _process(wired)
    original = __import__("zebra_agent_worker.command_process", fromlist=["CommandWakeupConsumer"])
    base_consumer = original.CommandWakeupConsumer
    waits = []

    class DeferredConsumer(base_consumer):
        async def poll(self, lane, **kwargs):
            log.append(lane)
            if lane == "execution":
                self._execution_discovery_generation += 1
            return (original.PickupOutcome.DEFERRED,)

    monkeypatch.setattr(original, "CommandWakeupConsumer", DeferredConsumer)
    wait_for = asyncio.wait_for

    async def observe(awaitable, timeout):
        waits.append(timeout)
        return await wait_for(awaitable, timeout)

    monkeypatch.setattr(asyncio, "wait_for", observe)
    result = process.run(worker_id="worker", max_cycles=4, idle_sleep_seconds=0)
    assert result.cycles_completed == 4
    assert "control" in log and "cleanup" in log
    assert len([value for value in waits if value == 0]) == 0
    assert max(waits) >= 0.2


@pytest.mark.parametrize("capacity, ceiling", [(False, 5), (True, 1)])
def test_background_error_backoff_is_capped_and_stop_interrupts(
    monkeypatch, caplog, capacity, ceiling
):
    from agent_storage.postgres.connection_capacity import DatabaseCapacityExceeded
    from zebra_agent_worker.command_background import background

    waits = []
    stop = asyncio.Event()
    attempts = 0

    async def action():
        nonlocal attempts
        attempts += 1
        if attempts == 24:
            stop.set()
        error = DatabaseCapacityExceeded if capacity else RuntimeError
        raise error("do-not-log-credentials")

    async def timeout(awaitable, seconds):
        waits.append(seconds)
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", timeout)
    asyncio.run(background(action, stop=stop, interval=0.05))
    assert attempts == 24
    assert all(0.05 <= wait <= ceiling for wait in waits)
    assert waits[-1] >= 0.8 * ceiling
    assert "do-not-log-credentials" not in caplog.text
    assert ("DatabaseCapacityExceeded" if capacity else "RuntimeError") in caplog.text


def test_local_blocked_loop_retains_existing_cadence(monkeypatch):
    delays = []
    service = WorkerLoopService(None, None, sleep=delays.append)
    monkeypatch.setattr(service, "poll_once", lambda **kw:
                        WorkerLoopCycleResult(("ready",), (), ("ready",)))
    result = service.run(worker_id="local", max_cycles=3)
    assert result.cycles_completed == 3
    assert delays == []


def test_control_signal_interrupts_deferred_execution_wait(wired, monkeypatch):
    import signal
    from time import monotonic

    from zebra_agent_worker import command_process as module

    log, *_ = wired
    consumer_type = module.CommandWakeupConsumer
    execution_polls = 0
    control_polls = 0
    handlers = {}
    signalled_at = None

    class DeferredConsumer(consumer_type):
        async def poll(self, lane, **kwargs):
            nonlocal execution_polls, control_polls, signalled_at
            if lane == "execution":
                execution_polls += 1
                self._execution_discovery_generation += 1
                return (module.PickupOutcome.DEFERRED,)
            control_polls += 1
            if execution_polls == 3 and signalled_at is None:
                signalled_at = monotonic()
                handlers[signal.SIGTERM]()
            return (module.PickupOutcome.ACKNOWLEDGED,)

    monkeypatch.setattr(module, "CommandWakeupConsumer", DeferredConsumer)

    async def check():
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "add_signal_handler",
                            lambda sig, callback: handlers.update({sig: callback}))
        monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: True)
        result = await _process(wired)._run("worker", 30, 100, False,
                                           idle_sleep_seconds=0)
        assert result.stop_reason == "signal"

    asyncio.run(check())
    assert execution_polls == 3 and control_polls >= 4
    assert signalled_at is not None and monotonic() - signalled_at < 0.5
    assert "consumer-drained" in log and "memory-drained" in log
