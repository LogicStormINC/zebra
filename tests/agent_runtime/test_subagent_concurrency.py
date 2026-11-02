"""Deterministic cancellation interleavings; no model, network or business work."""
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread

import pytest
from agent_core.domain.subagents import ResearchSubagentTask, SubagentStatus
from agent_runtime.subagents import LocalResearchSubagentCoordinator, cancelled_result


@pytest.mark.parametrize("reader", ["collect", "join"])
def test_cancelled_future_is_readable_before_cancel_returns(tmp_path: Path, monkeypatch, reader):
    # Hold the only executor thread so the actual child remains queued.
    executor = ThreadPoolExecutor(1)
    occupied, release_worker, in_callback, release_callback = (Event() for _ in range(4))

    def occupy():
        occupied.set()
        assert release_worker.wait(3)

    executor.submit(occupy)
    assert occupied.wait(2)
    coordinator = LocalResearchSubagentCoordinator(lambda *_: pytest.fail("queued child ran"))
    coordinator._executor.shutdown()
    coordinator._executor = executor
    original_submit = executor.submit

    def submit(*args, **kwargs):
        future = original_submit(*args, **kwargs)

        def pause_cancel(_):
            in_callback.set()
            assert release_callback.wait(3)

        future.add_done_callback(pause_cancel)
        return future

    monkeypatch.setattr(executor, "submit", submit)
    child = coordinator.spawn(ResearchSubagentTask(objective="inspect", workspace_root=tmp_path))
    cancelling = Thread(target=coordinator.cancel, args=(child,))
    cancelling.start()
    try:
        assert in_callback.wait(2)
        assert getattr(coordinator, reader)(child).status is SubagentStatus.CANCELLED
    finally:
        release_callback.set()
        release_worker.set()
        cancelling.join(2)
        coordinator.close()
    assert not cancelling.is_alive()
    assert coordinator.collect(child).status is SubagentStatus.CANCELLED
    assert coordinator.cancel(child) is False


def test_result_with_cancelled_error_is_not_a_cancelled_future(tmp_path: Path):
    from concurrent.futures import CancelledError

    coordinator = LocalResearchSubagentCoordinator(lambda child, *_: cancelled_result(child))
    child = coordinator.spawn(ResearchSubagentTask(objective="inspect", workspace_root=tmp_path))
    coordinator._records[child].future.result(timeout=2)
    future = Future()
    future.set_exception(CancelledError("runner failure"))
    coordinator._records[child].future = future
    try:
        for reader in (coordinator.join, coordinator.collect):
            with pytest.raises(CancelledError, match="runner failure"):
                reader(child)
    finally:
        coordinator.close()
